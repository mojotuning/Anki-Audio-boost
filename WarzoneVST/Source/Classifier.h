#pragma once
#ifndef NOMINMAX
 #define NOMINMAX
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <JuceHeader.h>
#include <vector>
#include <string>
#include <atomic>
#include <fstream>

// ─────────────────────────────────────────────────────────────────────────────
// WarzoneClassifier — Cliente IPC para WarzoneHelper.exe
//
// Corre en audiodg.exe (proceso PPL) donde Ort::Env no puede inicializarse.
// Lanza WarzoneHelper.exe (proceso normal) y se comunica via named pipe.
//
// Pipe: \\.\pipe\WarzoneAudioClassifier
// Protocolo:
//   Plugin -> Helper: uint32_t numSamples + float[numSamples]  (mono 22050 Hz)
//   Helper -> Plugin: float[4] { own_gun, enemy_gun, footstep, streak }
// ─────────────────────────────────────────────────────────────────────────────

class WarzoneClassifier : public juce::Thread
{
public:
    struct ClassProbs
    {
        // Default 0.0 = sin procesado hasta que el modelo clasifique algo.
        // Con 0.25 (equiprobable) el duck y el boost se aplicaban siempre
        // al 75% de intensidad aunque el modelo no estuviera cargado — bug critico.
        float own_gun   = 0.0f;
        float enemy_gun = 0.0f;
        float footstep  = 0.0f;
        float streak    = 0.0f;
    };

    WarzoneClassifier() : juce::Thread ("WarzoneClassifier") {}

    ~WarzoneClassifier()
    {
        // Cerrar el pipe primero cancela cualquier IO pendiente en el hilo bg
        if (_pipe != INVALID_HANDLE_VALUE)
        {
            CloseHandle (_pipe);
            _pipe = INVALID_HANDLE_VALUE;
        }
        stopThread (2000);
        if (_helperProc != INVALID_HANDLE_VALUE)
        {
            WaitForSingleObject (_helperProc, 500);
            TerminateProcess    (_helperProc, 0);
            CloseHandle         (_helperProc);
            _helperProc = INVALID_HANDLE_VALUE;
        }
    }

    // Lanza WarzoneHelper.exe (en la misma carpeta que este DLL) y conecta al pipe.
    // modelPath se ignora: el helper encuentra warzone_classifier.onnx en su dir.
    bool loadModel (const std::wstring& /*modelPath*/)
    {
        if (_connected.load()) return true;

        vlog ("loadModel: iniciando WarzoneHelper.exe");
        const std::wstring dllDir    = getDllDir();
        const std::wstring helperExe = dllDir + L"WarzoneHelper.exe";

        vlog (("helper: " + std::string (helperExe.begin(), helperExe.end())).c_str());

        STARTUPINFOW si = {};
        si.cb           = sizeof (si);
        si.dwFlags      = STARTF_USESHOWWINDOW;
        si.wShowWindow  = SW_HIDE;
        PROCESS_INFORMATION pi = {};

        if (! CreateProcessW (helperExe.c_str(), nullptr, nullptr, nullptr,
                              FALSE, CREATE_NO_WINDOW, nullptr,
                              dllDir.c_str(), &si, &pi))
        {
            _lastError = "CreateProcess FAILED (error " + std::to_string (GetLastError()) + ")";
            vlog (_lastError.c_str());
            return false;
        }
        CloseHandle (pi.hThread);
        _helperProc = pi.hProcess;

        vlog ("helper lanzado, conectando al pipe...");
        const char* PIPE_NAME = "\\\\.\\pipe\\WarzoneAudioClassifier";
        for (int attempt = 0; attempt < 25; ++attempt)
        {
            _pipe = CreateFileA (PIPE_NAME, GENERIC_READ | GENERIC_WRITE,
                                 0, nullptr, OPEN_EXISTING, 0, nullptr);
            if (_pipe != INVALID_HANDLE_VALUE) break;
            const DWORD err = GetLastError();
            if (err != ERROR_FILE_NOT_FOUND && err != ERROR_PIPE_BUSY)
            {
                _lastError = "CreateFile pipe FAILED (error " + std::to_string (err) + ")";
                vlog (_lastError.c_str());
                return false;
            }
            Sleep (100);
        }
        if (_pipe == INVALID_HANDLE_VALUE)
        {
            _lastError = "Timeout: sin conexion al pipe";
            vlog (_lastError.c_str());
            return false;
        }
        DWORD pipeMode = PIPE_READMODE_BYTE;
        SetNamedPipeHandleState (_pipe, &pipeMode, nullptr, nullptr);
        vlog ("pipe conectado OK");
        _connected.store (true);
        startThread (juce::Thread::Priority::background);
        return true;
    }

    const std::string& getLastError() const { return _lastError; }

    bool isModelLoaded() const { return _connected.load(); }

    void prepare (double sampleRate, int /*samplesPerBlock*/)
    {
        _pluginSR      = sampleRate;
        _resamplePhase = 0.0;
        _prevSample    = 0.0f;
        _audioBuf.assign (CLIP_SAMPLES, 0.0f);
        _audioBufCount = 0;
        _inferBuf.resize (CLIP_SAMPLES, 0.0f);
    }

    // Call once per audio block with the mono analysis signal.
    // Returns the last completed classification (updated every ~1 s).
    ClassProbs process (const float* mono, int numSamples)
    {
        // ── Linear-interpolation downsampler: plugin SR -> 22 050 Hz ─────────
        const double step = _pluginSR / double (TARGET_SR);
        for (int i = 0; i < numSamples; ++i)
        {
            const float cur = mono[i];
            _resamplePhase += 1.0;
            while (_resamplePhase >= step)
            {
                _resamplePhase -= step;
                if (_audioBufCount < CLIP_SAMPLES)
                {
                    const float t = float (_resamplePhase / step);
                    _audioBuf[_audioBufCount++] = _prevSample * t + cur * (1.0f - t);
                }
            }
            _prevSample = cur;
        }

        if (_audioBufCount >= CLIP_SAMPLES && ! _bufferReady.load())
        {
            {
                const juce::SpinLock::ScopedLockType sl (_inferBufLock);
                std::copy (_audioBuf.begin(), _audioBuf.end(), _inferBuf.begin());
            }
            _bufferReady.store (true);
            _audioBufCount = 0;
            _resamplePhase = 0.0;
        }

        const juce::SpinLock::ScopedLockType sl (_probsLock);
        return _lastProbs;
    }

private:
    static constexpr int TARGET_SR    = 22050;
    static constexpr int CLIP_SAMPLES = TARGET_SR;  // 1 segundo a 22050 Hz

    // ── IPC ───────────────────────────────────────────────────────────────────
    HANDLE            _pipe       = INVALID_HANDLE_VALUE;
    HANDLE            _helperProc = INVALID_HANDLE_VALUE;
    std::atomic<bool> _connected  { false };
    std::string       _lastError;

    // ── Acumulacion de audio (solo hilo de audio) ─────────────────────────────
    std::vector<float> _audioBuf;
    int                _audioBufCount = 0;
    double             _pluginSR      = 48000.0;
    double             _resamplePhase = 0.0;
    float              _prevSample    = 0.0f;

    // ── Buffer de inferencia (audio thread escribe, bg thread lee) ────────────
    std::vector<float> _inferBuf;
    std::atomic<bool>  _bufferReady { false };
    juce::SpinLock     _inferBufLock;

    // ── Resultado (bg thread escribe, audio thread lee) ───────────────────────
    ClassProbs     _lastProbs;
    juce::SpinLock _probsLock;

    // ── Hilo bg: envia audio -> recibe probabilidades ─────────────────────────
    void run() override
    {
        while (! threadShouldExit())
        {
            if (_bufferReady.exchange (false))
            {
                std::vector<float> localBuf (CLIP_SAMPLES);
                {
                    const juce::SpinLock::ScopedLockType sl (_inferBufLock);
                    localBuf = _inferBuf;
                }

                const uint32_t n = CLIP_SAMPLES;
                DWORD written = 0;
                if (! WriteFile (_pipe, &n, sizeof (n), &written, nullptr) ||
                    ! WriteFile (_pipe, localBuf.data(), n * sizeof (float), &written, nullptr))
                {
                    vlog ("bg: WriteFile FAILED — helper desconectado");
                    _connected.store (false);
                    break;
                }

                float result[4] = {};
                DWORD got = 0;
                if (! ReadFile (_pipe, result, sizeof (result), &got, nullptr) ||
                    got != sizeof (result))
                {
                    vlog ("bg: ReadFile FAILED — helper desconectado");
                    _connected.store (false);
                    break;
                }

                const juce::SpinLock::ScopedLockType sl (_probsLock);
                _lastProbs.own_gun   = result[0];
                _lastProbs.enemy_gun = result[1];
                _lastProbs.footstep  = result[2];
                _lastProbs.streak    = result[3];
            }
            sleep (5);
        }
    }

    // ── Devuelve el directorio de este DLL (terminado en '\') ─────────────────
    static std::wstring getDllDir()
    {
        HMODULE hm = nullptr;
        GetModuleHandleExW (
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
            GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR> (&getDllDir), &hm);
        wchar_t path[MAX_PATH] = {};
        GetModuleFileNameW (hm, path, MAX_PATH);
        std::wstring ws (path);
        const auto sl = ws.rfind (L'\\');
        return (sl != std::wstring::npos) ? ws.substr (0, sl + 1) : L"";
    }

    static void vlog (const char* msg)
    {
        std::ofstream f ("C:\\Temp\\warzone_vst.log", std::ios::app);
        if (! f.is_open()) return;
        f << "[IPC] " << msg << "\n";
    }

    JUCE_DECLARE_NON_COPYABLE (WarzoneClassifier)
};
