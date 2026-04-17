#include "PluginProcessor.h"
#include "PluginEditor.h"

#if defined (_WIN32)
 #ifndef WIN32_LEAN_AND_MEAN
  #define WIN32_LEAN_AND_MEAN
 #endif
 #include <windows.h>
 #include <fstream>
 #include <ctime>

// Log simple a archivo — visible desde ambos procesos (Editor.exe y audiodg.exe)
static void wrzLog (const char* msg)
{
    std::ofstream f ("C:\\Temp\\warzone_vst.log", std::ios::app);
    if (! f.is_open()) return;
    std::time_t t = std::time (nullptr);
    char buf[32]; std::strftime (buf, sizeof(buf), "%H:%M:%S", std::localtime (&t));
    f << "[" << buf << "] " << msg << "\n";
}
#else
static void wrzLog (const char*) {}
#endif

//──────────────────────────────────────────────────────────────────────────────
// Layout de parametros — todos los que se exponen al usuario en la UI
//──────────────────────────────────────────────────────────────────────────────
juce::AudioProcessorValueTreeState::ParameterLayout WarzoneProcessor::createParameterLayout()
{
    juce::AudioProcessorValueTreeState::ParameterLayout layout;

    // GUN TAMER
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        "gun_duck_db", "Gun Duck",
        juce::NormalisableRange<float> (-18.0f, 0.0f, 0.1f), -10.0f,
        juce::AudioParameterFloatAttributes().withLabel ("dB")));

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        "gun_attack_ms", "Gun Attack",
        juce::NormalisableRange<float> (1.0f, 30.0f, 0.5f), 5.0f,
        juce::AudioParameterFloatAttributes().withLabel ("ms")));

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        "gun_release_ms", "Gun Release",
        juce::NormalisableRange<float> (10.0f, 500.0f, 1.0f), 80.0f,
        juce::AudioParameterFloatAttributes().withLabel ("ms")));

    // FOOTSTEP
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        "foot_boost_db", "Foot Boost",
        juce::NormalisableRange<float> (0.0f, 12.0f, 0.1f), 9.0f,
        juce::AudioParameterFloatAttributes().withLabel ("dB")));

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        "foot_eq_gain_db", "Foot EQ 1.8kHz",
        juce::NormalisableRange<float> (0.0f, 6.0f, 0.1f), 3.0f,
        juce::AudioParameterFloatAttributes().withLabel ("dB")));

    // Segunda banda EQ para pasos lejanos (10-20m): crunch sube a 2-3kHz con la distancia
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        "foot_eq2_gain_db", "Foot EQ 2.5kHz",
        juce::NormalisableRange<float> (0.0f, 6.0f, 0.1f), 2.5f,
        juce::AudioParameterFloatAttributes().withLabel ("dB")));

    // STREAK
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        "strk_cut_db", "Streak Cut",
        juce::NormalisableRange<float> (-12.0f, 0.0f, 0.1f), -4.0f,
        juce::AudioParameterFloatAttributes().withLabel ("dB")));

    // MASTER
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        "master_gain_db", "Master Gain",
        juce::NormalisableRange<float> (-12.0f, 6.0f, 0.1f), 0.0f,
        juce::AudioParameterFloatAttributes().withLabel ("dB")));

    return layout;
}

//──────────────────────────────────────────────────────────────────────────────
WarzoneProcessor::WarzoneProcessor()
    : AudioProcessor (BusesProperties()
        .withInput  ("Input",  juce::AudioChannelSet::discreteChannels (16), true)
        .withOutput ("Output", juce::AudioChannelSet::discreteChannels (16), true)),
      apvts (*this, nullptr, "PARAMETERS", createParameterLayout())
{
    wrzLog ("constructor OK");
}

WarzoneProcessor::~WarzoneProcessor() {}

//──────────────────────────────────────────────────────────────────────────────
bool WarzoneProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    auto in  = layouts.getMainInputChannelSet();
    auto out = layouts.getMainOutputChannelSet();

    if (in != out) return false;

    // Aceptar cualquier configuracion entre 2 y 16 canales discretos
    int n = in.size();
    return (n >= 2 && n <= 16);
}

//──────────────────────────────────────────────────────────────────────────────
void WarzoneProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    int numCh = getTotalNumInputChannels();

#if defined (_WIN32)
    // Resolver la ruta del modelo una sola vez.
    // Hacerlo aqui (no en el constructor) evita el crash 0xC0000005:
    // en el constructor el proceso de APO aun no tiene el contexto necesario
    // para que Ort::Env se inicialice correctamente.
    if (_modelPath.empty())
    {
        wchar_t dllPath[MAX_PATH] = {};
        HMODULE hMod = nullptr;
        GetModuleHandleExW (
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR> (&createPluginFilter),
            &hMod);
        GetModuleFileNameW (hMod, dllPath, MAX_PATH);
        std::wstring p (dllPath);
        const auto slash = p.rfind (L'\\');
        if (slash != std::wstring::npos)
            _modelPath = p.substr (0, slash + 1) + L"warzone_classifier.onnx";
    }

    // Cargar el modelo sincrono — prepareToPlay corre antes de cualquier audio,
    // no es tiempo real, puede hacer I/O. Solo se intenta una vez.
    if (! _modelLoadAttempted.exchange (true))
    {
        wrzLog (("loadModel path: " + juce::String (_modelPath.c_str()).toStdString()).c_str());
        bool ok = classifier.loadModel (_modelPath);
        if (ok)
            wrzLog ("loadModel OK — ONNX corriendo");
        else
            wrzLog (("loadModel FAILED: " + classifier.getLastError()).c_str());
    }
#endif

    classifier.prepare (sampleRate, samplesPerBlock);
    audioProcessor.prepare (sampleRate, samplesPerBlock, numCh);

    monoAnalysisBuf.setSize (1, samplesPerBlock);
    monoAnalysisBuf.clear();
}

void WarzoneProcessor::releaseResources() {}

//──────────────────────────────────────────────────────────────────────────────
void WarzoneProcessor::processBlock (juce::AudioBuffer<float>& buffer,
                                     juce::MidiBuffer& /*midiMessages*/)
{
    juce::ScopedNoDenormals noDenormals;

    const int numSamples = buffer.getNumSamples();
    const int numCh      = buffer.getNumChannels();

    // ── Leer parametros actuales del APVTS ─────────────────────────────────
    ClassAwareProcessor::Params p;
    p.gunDuckDb    = apvts.getRawParameterValue ("gun_duck_db")->load();
    p.gunAttackMs  = apvts.getRawParameterValue ("gun_attack_ms")->load();
    p.gunReleaseMs = apvts.getRawParameterValue ("gun_release_ms")->load();
    p.footBoostDb  = apvts.getRawParameterValue ("foot_boost_db")->load();
    p.footEqGainDb  = apvts.getRawParameterValue ("foot_eq_gain_db")->load();
    p.footEq2GainDb = apvts.getRawParameterValue ("foot_eq2_gain_db")->load();
    p.strkCutDb    = apvts.getRawParameterValue ("strk_cut_db")->load();
    p.masterGainDb = apvts.getRawParameterValue ("master_gain_db")->load();
    audioProcessor.notifyParamsChanged (p);

    // ── Mix mono para analisis: TODOS los canales excepto LFE (ch 3) ──────────
    // CRITICO: usar solo L+R significa que los pasos del enemigo en surround
    // (SL SR BL BR) jamas llegan al clasificador. El modelo nunca los escucha.
    monoAnalysisBuf.setSize (1, numSamples, false, false, true);
    monoAnalysisBuf.clear();
    {
        int analysisChs = 0;
        for (int ch = 0; ch < numCh; ++ch)
            if (ch != 3) ++analysisChs;  // saltar LFE
        const float w = analysisChs > 0 ? 1.0f / float (analysisChs) : 1.0f;
        for (int ch = 0; ch < numCh; ++ch)
            if (ch != 3)
                monoAnalysisBuf.addFrom (0, 0, buffer, ch, 0, numSamples, w);
    }

    // ── Clasificacion ───────────────────────────────────────────────────────
    WarzoneClassifier::ClassProbs probs = classifier.process (monoAnalysisBuf.getReadPointer (0), numSamples);

    // Publicar al editor (hilo de audio -> hilo de UI, sin locks)
    classProbAmb.store  (probs.enemy_gun);
    classProbFoot.store (probs.footstep);
    classProbGun.store  (probs.own_gun);
    classProbStrk.store (probs.streak);

    // ── Procesamiento guiado por clase ──────────────────────────────────────
    audioProcessor.process (buffer, probs);
}

//──────────────────────────────────────────────────────────────────────────────
juce::AudioProcessorEditor* WarzoneProcessor::createEditor()
{
    return new WarzoneEditor (*this);
}

//──────────────────────────────────────────────────────────────────────────────
void WarzoneProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    auto state = apvts.copyState();
    std::unique_ptr<juce::XmlElement> xml (state.createXml());
    copyXmlToBinary (*xml, destData);
}

void WarzoneProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    std::unique_ptr<juce::XmlElement> xml (getXmlFromBinary (data, sizeInBytes));
    if (xml != nullptr && xml->hasTagName (apvts.state.getType()))
        apvts.replaceState (juce::ValueTree::fromXml (*xml));
}

//──────────────────────────────────────────────────────────────────────────────
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new WarzoneProcessor();
}
