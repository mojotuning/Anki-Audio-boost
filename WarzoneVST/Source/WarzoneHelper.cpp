// WarzoneHelper.exe
// Proceso separado que corre ONNX fuera de audiodg.exe (proceso PPL donde ONNX no puede inicializarse).
// El plugin VST lo lanza automaticamente y se comunica via named pipe.
//
// Protocolo del pipe "\\.\pipe\WarzoneAudioClassifier":
//   Plugin -> Helper: uint32_t numSamples + float[numSamples]  (audio mono 22050 Hz)
//   Helper -> Plugin: float[4]  { own_gun, enemy_gun, footstep, streak }
//
// El helper acepta conexiones en bucle. Se termina cuando el plugin cierra el pipe
// o cuando recibe numSamples == 0 (senal de shutdown).

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <onnxruntime_cxx_api.h>

#include <vector>
#include <array>
#include <string>
#include <cmath>
#include <algorithm>
#include <fstream>
#include <ctime>

// ── Constantes (deben coincidir exactamente con el entrenamiento Python) ──────
static constexpr int   TARGET_SR    = 22050;
static constexpr int   CLIP_SAMPLES = TARGET_SR;
static constexpr int   N_MELS       = 64;
static constexpr int   N_FFT        = 1024;
static constexpr int   HOP          = 256;
static constexpr float FMIN         = 50.0f;
static constexpr float FMAX         = 11025.0f;
static constexpr int   N_FRAMES     = 87;
static constexpr int   N_BINS       = N_FFT / 2 + 1;  // 513

static constexpr DWORD PIPE_TIMEOUT_MS = 5000;
static constexpr DWORD PIPE_BUFSIZE    = 1024 * 1024;  // 1 MB

// ── Logging ───────────────────────────────────────────────────────────────────
static void hlog(const char* msg)
{
    std::ofstream f("C:\\Temp\\warzone_helper.log", std::ios::app);
    if (!f.is_open()) return;
    std::time_t t = std::time(nullptr);
    char buf[32]; std::strftime(buf, sizeof(buf), "%H:%M:%S", std::localtime(&t));
    f << "[" << buf << "] " << msg << "\n";
    f.flush();
}

// ── Mel filterbank ────────────────────────────────────────────────────────────
static float hzToMel(float hz) { return 2595.0f * std::log10(1.0f + hz / 700.0f); }
static float melToHz(float mel) { return 700.0f * (std::pow(10.0f, mel / 2595.0f) - 1.0f); }

static std::vector<std::vector<float>> buildMelFilterbank()
{
    const int   numPts = N_MELS + 2;
    const float melMin = hzToMel(FMIN);
    const float melMax = hzToMel(FMAX);

    std::vector<float> fPts(numPts);
    for (int i = 0; i < numPts; ++i)
    {
        const float m = melMin + float(i) / float(numPts - 1) * (melMax - melMin);
        fPts[i] = melToHz(m);
    }

    std::vector<float> freqs(N_BINS);
    for (int k = 0; k < N_BINS; ++k)
        freqs[k] = float(k) * float(TARGET_SR) / float(N_FFT);

    std::vector<std::vector<float>> fb(N_MELS, std::vector<float>(N_BINS, 0.0f));
    for (int m = 0; m < N_MELS; ++m)
    {
        const float fLow  = fPts[m];
        const float fPeak = fPts[m + 1];
        const float fHigh = fPts[m + 2];
        for (int k = 0; k < N_BINS; ++k)
        {
            const float f = freqs[k];
            if      (f >= fLow  && f <  fPeak) fb[m][k] = (f - fLow)  / (fPeak - fLow);
            else if (f >= fPeak && f <= fHigh)  fb[m][k] = (fHigh - f) / (fHigh - fPeak);
        }
    }
    return fb;
}

// ── Hann window ───────────────────────────────────────────────────────────────
static std::vector<float> buildHannWindow()
{
    std::vector<float> w(N_FFT);
    for (int n = 0; n < N_FFT; ++n)
        w[n] = 0.5f * (1.0f - std::cos(2.0f * 3.14159265f * float(n) / float(N_FFT - 1)));
    return w;
}

// ── FFT Cooley-Tukey in-place (real forward, magnitude output) ────────────────
// Calcula |X[k]|^2 para k = 0..N_FFT/2 en el buffer in-place.
// Entrada: data[0..N_FFT-1] windowed real samples; data[N_FFT..] = 0
// Salida:  data[0..N_BINS-1] = power spectrum |X[k]|^2
static void computePowerSpectrum(std::vector<float>& data)
{
    // Bit-reversal permutation
    const int n  = N_FFT;
    const int hn = n / 2;
    int j = 0;
    for (int i = 1; i < n; ++i)
    {
        int bit = hn;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) { std::swap(data[i], data[j]); }
    }

    // FFT butterfly (using interleaved real/imag — re at 2k, im at 2k+1 in work buf)
    // We use a 2N real buffer: data_re[0..N-1] + data_im[0..N-1]
    std::vector<float> re(data.begin(), data.begin() + n);
    std::vector<float> im(n, 0.0f);

    for (int len = 2; len <= n; len <<= 1)
    {
        const float ang = -2.0f * 3.14159265358979f / float(len);
        const float wRe = std::cos(ang);
        const float wIm = std::sin(ang);
        for (int i = 0; i < n; i += len)
        {
            float uRe = 1.0f, uIm = 0.0f;
            for (int k = 0; k < len / 2; ++k)
            {
                const float tRe = uRe * re[i + k + len/2] - uIm * im[i + k + len/2];
                const float tIm = uRe * im[i + k + len/2] + uIm * re[i + k + len/2];
                re[i + k + len/2] = re[i + k] - tRe;
                im[i + k + len/2] = im[i + k] - tIm;
                re[i + k] += tRe;
                im[i + k] += tIm;
                const float nRe = uRe * wRe - uIm * wIm;
                uIm = uRe * wIm + uIm * wRe;
                uRe = nRe;
            }
        }
    }

    // Power spectrum: |X[k]|^2 for k=0..N_BINS-1
    for (int k = 0; k < N_BINS; ++k)
        data[k] = re[k] * re[k] + im[k] * im[k];
}

// ── Clasificador ──────────────────────────────────────────────────────────────
struct ClassProbs { float own_gun, enemy_gun, footstep, streak; };

static ClassProbs runInference(
    Ort::Session&                               session,
    const std::vector<std::vector<float>>&      filterbank,
    const std::vector<float>&                   hannWindow,
    const std::vector<float>&                   rawAudio)
{
    // 1. RMS normalize
    float sum2 = 0.0f;
    for (float s : rawAudio) sum2 += s * s;
    const float rms = std::sqrt(sum2 / float(rawAudio.size()));
    std::vector<float> y(rawAudio);
    if (rms > 1e-6f)
        for (auto& s : y)
            s = std::max(-4.0f, std::min(4.0f, s / rms));

    // 2. Reflect-pad (N_FFT/2 = 512 per side)
    const int PAD = N_FFT / 2;
    std::vector<float> padded(PAD + CLIP_SAMPLES + PAD);
    for (int i = 0; i < PAD; ++i)    padded[i]                      = y[PAD - 1 - i];
    std::copy(y.begin(), y.end(),     padded.begin() + PAD);
    for (int i = 0; i < PAD; ++i)    padded[PAD + CLIP_SAMPLES + i] = y[CLIP_SAMPLES - 1 - i];

    // 3. STFT -> mel power
    std::vector<float> melSpec(N_MELS * N_FRAMES, 0.0f);
    std::vector<float> work(N_FFT * 2, 0.0f);
    for (int t = 0; t < N_FRAMES; ++t)
    {
        const int start = t * HOP;
        for (int n = 0; n < N_FFT; ++n)
            work[n] = padded[start + n] * hannWindow[n];
        std::fill(work.begin() + N_FFT, work.end(), 0.0f);

        computePowerSpectrum(work);

        for (int m = 0; m < N_MELS; ++m)
        {
            float val = 0.0f;
            for (int k = 0; k < N_BINS; ++k)
                val += filterbank[m][k] * work[k];
            melSpec[m * N_FRAMES + t] = val;
        }
    }

    // 4. AmplitudeToDB, 80dB floor
    float maxDb = -1e30f;
    for (auto& s : melSpec)
    {
        s = 10.0f * std::log10(std::max(s, 1e-10f));
        if (s > maxDb) maxDb = s;
    }
    const float dbFloor = maxDb - 80.0f;
    for (auto& s : melSpec)
        if (s < dbFloor) s = dbFloor;

    // 5. Normalize to [-1, 1]
    const float vMin  = *std::min_element(melSpec.begin(), melSpec.end());
    const float range = maxDb - vMin + 1e-6f;
    for (auto& s : melSpec)
        s = (s - vMin) / range * 2.0f - 1.0f;

    // 6. ONNX inference
    Ort::MemoryInfo memInfo = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    const std::array<int64_t, 4> shape{ 1, 1, int64_t(N_MELS), int64_t(N_FRAMES) };
    auto inputTensor = Ort::Value::CreateTensor<float>(
        memInfo, melSpec.data(), melSpec.size(), shape.data(), shape.size());

    const char* inNames[]  = { "mel_spectrogram" };
    const char* outNames[] = { "class_logits" };
    auto outputs = session.Run(Ort::RunOptions{ nullptr }, inNames, &inputTensor, 1, outNames, 1);

    const float* logits = outputs[0].GetTensorData<float>();
    const float  maxL   = *std::max_element(logits, logits + 4);
    float exps[4], expSum = 0.0f;
    for (int i = 0; i < 4; ++i) { exps[i] = std::exp(logits[i] - maxL); expSum += exps[i]; }

    return { exps[0]/expSum, exps[1]/expSum, exps[2]/expSum, exps[3]/expSum };
}

// ── Pipe helpers ──────────────────────────────────────────────────────────────
// Lectura completa — ReadFile en pipe de bytes puede devolver menos de lo pedido
static bool pipeRead(HANDLE pipe, void* buf, DWORD bytes)
{
    DWORD total = 0;
    while (total < bytes)
    {
        DWORD got = 0;
        if (!ReadFile(pipe, static_cast<char*>(buf) + total, bytes - total, &got, nullptr) || got == 0)
            return false;
        total += got;
    }
    return true;
}

static bool pipeWrite(HANDLE pipe, const void* buf, DWORD bytes)
{
    DWORD total = 0;
    while (total < bytes)
    {
        DWORD written = 0;
        if (!WriteFile(pipe, static_cast<const char*>(buf) + total, bytes - total, &written, nullptr) || written == 0)
            return false;
        total += written;
    }
    return true;
}

// ── Main ──────────────────────────────────────────────────────────────────────
int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR cmdLine, int)
{
    hlog("WarzoneHelper iniciado");

    // Buscar el modelo .onnx en la misma carpeta que este exe
    char exePath[MAX_PATH] = {};
    GetModuleFileNameA(nullptr, exePath, MAX_PATH);
    std::string modelPath(exePath);
    const auto slash = modelPath.rfind('\\');
    if (slash != std::string::npos) modelPath = modelPath.substr(0, slash + 1);
    modelPath += "warzone_classifier.onnx";

    hlog(("Cargando modelo: " + modelPath).c_str());

    // Inicializar ONNX Runtime (aqui SI funcionan los threads, no es PPL)
    Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "WarzoneHelper");
    Ort::SessionOptions opts;
    opts.SetIntraOpNumThreads(2);
    opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

    std::unique_ptr<Ort::Session> session;
    try
    {
        std::wstring wPath(modelPath.begin(), modelPath.end());
        session = std::make_unique<Ort::Session>(env, wPath.c_str(), opts);
        hlog("Modelo ONNX cargado OK");
    }
    catch (const std::exception& e)
    {
        hlog(("ERROR cargando modelo: " + std::string(e.what())).c_str());
        return 1;
    }

    const auto filterbank = buildMelFilterbank();
    const auto hannWindow = buildHannWindow();
    hlog("Filterbank y Hann window listos");

    // Named pipe — acepta conexiones en bucle
    const char* PIPE_NAME = "\\\\.\\pipe\\WarzoneAudioClassifier";

    // NULL DACL: cualquier proceso (incluido audiodg.exe PPL) puede conectar al pipe.
    // Sin esto, audiodg.exe recibe ERROR_ACCESS_DENIED aunque sea el mismo usuario.
    SECURITY_DESCRIPTOR sd;
    InitializeSecurityDescriptor(&sd, SECURITY_DESCRIPTOR_REVISION);
    SetSecurityDescriptorDacl(&sd, TRUE, NULL, FALSE);
    SECURITY_ATTRIBUTES sa = { sizeof(sa), &sd, FALSE };

    for (;;)
    {
        HANDLE pipe = CreateNamedPipeA(
            PIPE_NAME,
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
            PIPE_UNLIMITED_INSTANCES,  // multiples instancias para multiples plugins
            PIPE_BUFSIZE,
            PIPE_BUFSIZE,
            PIPE_TIMEOUT_MS,
            &sa);  // NULL DACL — acceso permitido a todo proceso

        if (pipe == INVALID_HANDLE_VALUE)
        {
            hlog(("ERROR: CreateNamedPipe fallo, code=" + std::to_string(GetLastError())).c_str());
            Sleep(1000);
            continue;
        }

        hlog("Esperando conexion del plugin...");
        if (!ConnectNamedPipe(pipe, nullptr))
        {
            const DWORD err = GetLastError();
            if (err != ERROR_PIPE_CONNECTED)
            {
                CloseHandle(pipe);
                continue;
            }
        }
        hlog("Plugin conectado");

        // Bucle de inferencia por conexion
        for (;;)
        {
            uint32_t numSamples = 0;
            if (!pipeRead(pipe, &numSamples, sizeof(numSamples)))
                break;

            if (numSamples == 0)  // senal de shutdown
            {
                hlog("Shutdown recibido");
                CloseHandle(pipe);
                return 0;
            }

            std::vector<float> audio(numSamples);
            if (!pipeRead(pipe, audio.data(), numSamples * sizeof(float)))
                break;

            ClassProbs p = { 0.0f, 0.0f, 0.0f, 0.0f };
            try
            {
                p = runInference(*session, filterbank, hannWindow, audio);
                char logbuf[128];
                std::snprintf(logbuf, sizeof(logbuf),
                    "Inferencia OK: own=%.2f enemy=%.2f foot=%.2f streak=%.2f",
                    p.own_gun, p.enemy_gun, p.footstep, p.streak);
                hlog(logbuf);
            }
            catch (...) { hlog("EXCEPCION en runInference"); }

            float result[4] = { p.own_gun, p.enemy_gun, p.footstep, p.streak };
            if (!pipeWrite(pipe, result, sizeof(result)))
                break;
        }

        hlog("Plugin desconectado, esperando nueva conexion...");
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
    }
}
