#pragma once
#include <JuceHeader.h>
#include "Classifier.h"

// ─────────────────────────────────────────────────────────────────────────────
// ClassAwareProcessor — Procesador de 16 canales guiado por clasificacion
//
// Aplica diferentes cadenas de ganancia y EQ segun la clase detectada.
// Todo el procesamiento es suavizado para evitar clicks al cambiar de clase.
//
// Canales esperados (16ch Windows default de Warzone):
//   0=L  1=R  2=C  3=LFE  4=SL  5=SR  6=BL  7=BR
//   8=FHL 9=FHR 10=TFL 11=TFR 12=TRL 13=TRR 14=TSL 15=TSR
//
// Procesamiento por clase:
//   GUN  → duck rapido en canales frontales (L R C), -6dB, attack 2ms
//   FOOT → boost upward en canales surround (SL SR BL BR + altura),
//           peaking eq 1800 Hz +3dB
//   STRK → cut 400-800 Hz en todos los canales, -4dB
//   AMB  → paso limpio, ligero high-shelf +1dB > 8kHz para presencia
// ─────────────────────────────────────────────────────────────────────────────

class ClassAwareProcessor
{
public:
    // Parametros ajustables expuestos al usuario
    struct Params
    {
        // GUN
        float gunDuckDb     = -10.0f;
        float gunAttackMs   =   2.0f;
        float gunReleaseMs  =  80.0f;

        // FOOT
        float footBoostDb    =   9.0f;
        // Banda 1: crunch de pasos cercanos (gravilla, madera)
        float footEqFreq     = 1800.0f;
        float footEqGainDb   =   3.0f;
        float footEqQ        =   1.2f;
        // Banda 2: crunch de pasos a distancia media 10-20m
        float footEq2Freq    = 2500.0f;
        float footEq2GainDb  =   2.5f;
        float footEq2Q       =   1.0f;

        // STRK
        float strkCutDb     =  -4.0f;
        float strkFreq      = 600.0f;
        float strkQ         =   2.0f;

        // General
        float masterGainDb  =   0.0f;
    };

    ClassAwareProcessor() = default;

    void setParams (const Params& p) { pendingParams = p; }

    void prepare (double sampleRate, int samplesPerBlock, int numChannels)
    {
        sr          = sampleRate;
        blockSize   = samplesPerBlock;
        numCh       = numChannels;

        // Coeficientes de ataque/release para la envolvente de ganancia
        updateEnvelopes (params);

        // Filtros peaking para FOOT: uno por canal surround (4-7 y 8-15)
        // Los coeficientes son iguales para todos — preparamos uno y reutilizamos
        footEqFilters.resize  ((size_t) numChannels);
        footEq2Filters.resize ((size_t) numChannels);
        strkEqFilters.resize  ((size_t) numChannels);
        airShelfFilters.resize((size_t) numChannels);

        for (int ch = 0; ch < numChannels; ++ch)
        {
            footEqFilters[ch].coefficients = juce::dsp::IIR::Coefficients<float>::makePeakFilter (
                sr, params.footEqFreq, params.footEqQ, juce::Decibels::decibelsToGain (params.footEqGainDb));

            // Banda 2: peaking 2.5kHz, Q=1.0, +2.5dB
            // Captura el crunch de pasos a distancia media donde 1.8kHz se debilita
            footEq2Filters[ch].coefficients = juce::dsp::IIR::Coefficients<float>::makePeakFilter (
                sr, params.footEq2Freq, params.footEq2Q, juce::Decibels::decibelsToGain (params.footEq2GainDb));

            strkEqFilters[ch].coefficients = juce::dsp::IIR::Coefficients<float>::makePeakFilter (
                sr, params.strkFreq, params.strkQ, juce::Decibels::decibelsToGain (params.strkCutDb));

            // Air shelf: +1.5dB por encima de 8kHz para presencia en ambiente
            airShelfFilters[ch].coefficients = juce::dsp::IIR::Coefficients<float>::makeHighShelf (
                sr, 8000.0f, 0.707f, juce::Decibels::decibelsToGain (1.5f));

            footEqFilters[ch].reset();
            footEq2Filters[ch].reset();
            strkEqFilters[ch].reset();
            airShelfFilters[ch].reset();
        }

        // Ganancias por canal — inicializar en 1.0 (sin cambio)
        channelGain.assign ((size_t) numChannels, 1.0f);
        channelGainSmooth.assign ((size_t) numChannels, 1.0f);

        params = pendingParams;
    }

    // Procesa el buffer completo. probs viene del Classifier.
    void process (juce::AudioBuffer<float>& buffer, const WarzoneClassifier::ClassProbs& probs)
    {
        // Aplicar nuevos params si cambiaron
        if (paramsChanged.exchange (false))
        {
            params = pendingParams;
            updateEnvelopes (params);
            rebuildFilters();
        }

        const int numSamples = buffer.getNumSamples();
        const int actualCh   = std::min (buffer.getNumChannels(), numCh);

        // ── Calcular ganancias objetivo por canal segun clase ──────────────────

        // Canales frontales: L R C (ch 0,1,2)
        float frontTarget = 1.0f;

        // Duck por disparo propio: threshold 30%.
        if (probs.own_gun > 0.30f)
        {
            float duckGain = juce::Decibels::decibelsToGain (params.gunDuckDb);
            float blend    = juce::jlimit (0.0f, 1.0f, (probs.own_gun - 0.30f) / 0.70f);
            frontTarget = 1.0f + blend * (duckGain - 1.0f);
        }

        // Boost enemy_gun: threshold bajo (15%) porque el modelo raramente supera 50%
        // en gameplay real. +5dB para que se escuche claramente.
        // Solo aplica si NO se esta duckeando por disparo propio.
        if (probs.own_gun < 0.20f && probs.enemy_gun > 0.15f)
        {
            float boostGain = juce::Decibels::decibelsToGain (5.0f);
            float blend     = juce::jlimit (0.0f, 1.0f, (probs.enemy_gun - 0.15f) / 0.85f);
            frontTarget = 1.0f + blend * (boostGain - 1.0f);
        }

        // Canales surround — boost de pasos SOLO si no estamos disparando.
        // El modelo no distingue pasos propios de enemigos — si el usuario
        // dispara (own_gun > 20%) es probable que los pasos sean suyos.
        float surroundTarget = 1.0f;
        if (probs.footstep > 0.30f && probs.own_gun < 0.20f)
        {
            float boostGain = juce::Decibels::decibelsToGain (params.footBoostDb);
            float blend     = juce::jlimit (0.0f, 1.0f, (probs.footstep - 0.30f) / 0.70f);
            surroundTarget = 1.0f + blend * (boostGain - 1.0f);
        }

        // Ganancia maestra
        float masterGain = juce::Decibels::decibelsToGain (params.masterGainDb);

        // Asignar ganancias objetivo por indice de canal
        for (int ch = 0; ch < actualCh; ++ch)
        {
            float target;
            if      (ch == 3)            target = 1.0f;          // LFE: sin tocar
            else if (ch <= 2)            target = frontTarget;    // L R C
            else                         target = surroundTarget; // surround + altura

            channelGain[ch] = target * masterGain;
        }

        // ── Procesar sample a sample con suavizado de ganancia ─────────────────
        // El suavizado evita clicks al cambiar rapidamente de clase

        for (int ch = 0; ch < actualCh; ++ch)
        {
            float* data        = buffer.getWritePointer (ch);
            float  targetGain  = channelGain[ch];
            float  currentGain = channelGainSmooth[ch];

            // Coeficiente de suavizado: ataque o release segun direccion
            float coeff = (targetGain < currentGain) ? gainAttackCoeff : gainReleaseCoeff;

            for (int i = 0; i < numSamples; ++i)
            {
                currentGain += coeff * (targetGain - currentGain);
                data[i] *= currentGain;
            }

            channelGainSmooth[ch] = currentGain;

            // ── EQ por clase ────────────────────────────────────────────────────

            bool isSurround = (ch >= 4);

            // FOOT peaking EQ: todos los canales (pasos enemigos pueden venir de cualquier
            // lado), pero SOLO si no estamos disparando (own_gun < 20%).
            // El modelo incluye pasos propios en la clase footstep — si el usuario
            // dispara, es probable que los pasos detectados sean suyos.
            if (probs.footstep > 0.30f && probs.own_gun < 0.20f)
            {
                float wet = juce::jlimit (0.0f, 1.0f, (probs.footstep - 0.30f) / 0.70f);
                // Banda 1: 1.8kHz — pasos cercanos
                for (int i = 0; i < numSamples; ++i)
                {
                    float filtered = footEqFilters[ch].processSample (data[i]);
                    data[i] = data[i] + wet * (filtered - data[i]);
                }
                // Banda 2: 2.5kHz — pasos a 10-20m donde el crunch sube en freq
                for (int i = 0; i < numSamples; ++i)
                {
                    float filtered = footEq2Filters[ch].processSample (data[i]);
                    data[i] = data[i] + wet * (filtered - data[i]);
                }
            }

            // STRK notch EQ: todos los canales, threshold 30%
            if (probs.streak > 0.30f)
            {
                float wet = juce::jlimit (0.0f, 1.0f, (probs.streak - 0.30f) / 0.70f);
                for (int i = 0; i < numSamples; ++i)
                {
                    float filtered = strkEqFilters[ch].processSample (data[i]);
                    data[i] = data[i] + wet * (filtered - data[i]);
                }
            }
        }
    }

    // Llamar cuando el usuario cambia parametros desde el editor
    void notifyParamsChanged (const Params& p)
    {
        pendingParams  = p;
        paramsChanged  = true;
    }

private:
    void updateEnvelopes (const Params& p)
    {
        // Coeficientes para suavizado de ganancia por muestra
        gainAttackCoeff  = 1.0f - std::exp (-1.0f / (float (sr) * p.gunAttackMs  / 1000.0f));
        gainReleaseCoeff = 1.0f - std::exp (-1.0f / (float (sr) * p.gunReleaseMs / 1000.0f));
    }

    void rebuildFilters()
    {
        for (int ch = 0; ch < numCh; ++ch)
        {
            footEqFilters[ch].coefficients = juce::dsp::IIR::Coefficients<float>::makePeakFilter (
                sr, params.footEqFreq, params.footEqQ,
                juce::Decibels::decibelsToGain (params.footEqGainDb));

            footEq2Filters[ch].coefficients = juce::dsp::IIR::Coefficients<float>::makePeakFilter (
                sr, params.footEq2Freq, params.footEq2Q,
                juce::Decibels::decibelsToGain (params.footEq2GainDb));

            strkEqFilters[ch].coefficients = juce::dsp::IIR::Coefficients<float>::makePeakFilter (
                sr, params.strkFreq, params.strkQ,
                juce::Decibels::decibelsToGain (params.strkCutDb));
        }
    }

    double sr        = 48000.0;
    int    blockSize = 512;
    int    numCh     = 16;

    Params params;
    Params pendingParams;
    std::atomic<bool> paramsChanged { false };

    float gainAttackCoeff  = 0.0f;
    float gainReleaseCoeff = 0.0f;

    std::vector<float> channelGain;
    std::vector<float> channelGainSmooth;

    std::vector<juce::dsp::IIR::Filter<float>> footEqFilters;
    std::vector<juce::dsp::IIR::Filter<float>> footEq2Filters;
    std::vector<juce::dsp::IIR::Filter<float>> strkEqFilters;
    std::vector<juce::dsp::IIR::Filter<float>> airShelfFilters;

    JUCE_DECLARE_NON_COPYABLE (ClassAwareProcessor)
};
