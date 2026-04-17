cmake_minimum_required(VERSION 3.22)
project(WarzoneVST VERSION 1.0.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ONNX Runtime 1.20.1 — prebuilt CPU, x64
set(ORT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/onnxruntime")

# JUCE debe estar en WarzoneVST/JUCE (lo clona setup.ps1)
add_subdirectory(JUCE)

# VST2 SDK path — clonado por setup.ps1
juce_set_vst2_sdk_path("${CMAKE_CURRENT_SOURCE_DIR}/VST2_SDK")

juce_add_plugin(WarzoneProcessor
    PLUGIN_MANUFACTURER_CODE  Wzmj
    PLUGIN_CODE               Wrz1
    FORMATS                   VST VST3
    PRODUCT_NAME              "Warzone Audio Processor"
    PLUGIN_MANUFACTURER_NAME  "MojoTuning"
    DESCRIPTION               "16ch competitive audio enhancer for Warzone"
    IS_SYNTH                  FALSE
    NEEDS_MIDI_INPUT          FALSE
    NEEDS_MIDI_OUTPUT         FALSE
    IS_MIDI_EFFECT            FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS FALSE
    VST3_CATEGORIES           "Fx"
    COPY_PLUGIN_AFTER_BUILD   FALSE
)

juce_generate_juce_header(WarzoneProcessor)

target_sources(WarzoneProcessor PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginEditor.cpp
)

target_include_directories(WarzoneProcessor PRIVATE
    Source
    ${ORT_DIR}/include
)

target_compile_definitions(WarzoneProcessor PUBLIC
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
)

# /EHa: habilitar captura de excepciones SEH (0xC0000005) con catch(...)
# Sin esto, Ort::Env crashea silenciosamente en audiodg.exe sin que lo veamos
if (MSVC)
    target_compile_options(WarzoneProcessor PRIVATE /EHa)
endif()

target_link_libraries(WarzoneProcessor PRIVATE
    juce::juce_audio_utils
    juce::juce_dsp
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags
)

# Copy ONNX Runtime DLLs + model to the VST2 output folder
add_custom_command(TARGET WarzoneProcessor POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${ORT_DIR}/lib/onnxruntime.dll"
        "${ORT_DIR}/lib/onnxruntime_providers_shared.dll"
        "${CMAKE_CURRENT_SOURCE_DIR}/warzone_classifier.onnx"
        "${CMAKE_BINARY_DIR}/WarzoneProcessor_artefacts/$<CONFIG>/VST/"
    COMMENT "Copying onnxruntime DLLs + model to VST2 output folder"
)

# Copy ONNX Runtime DLLs + model to the VST3 bundle (x86_64-win) — one file at a time para evitar
# problemas de espacios en rutas con cmake -E copy_if_different multisource
set(VST3_WIN_DIR "${CMAKE_BINARY_DIR}/WarzoneProcessor_artefacts/$<CONFIG>/VST3/Warzone Audio Processor.vst3/Contents/x86_64-win")
foreach(_dll
    "${ORT_DIR}/lib/onnxruntime.dll"
    "${ORT_DIR}/lib/onnxruntime_providers_shared.dll"
    "${CMAKE_CURRENT_SOURCE_DIR}/warzone_classifier.onnx")
    add_custom_command(TARGET WarzoneProcessor POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${VST3_WIN_DIR}"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different "${_dll}" "${VST3_WIN_DIR}/"
        COMMENT "Copying ${_dll} to VST3 bundle"
    )
endforeach()

# ── WarzoneHelper.exe ─────────────────────────────────────────────────────────
# Proceso separado que corre ONNX fuera de audiodg.exe (proceso PPL).
# Se despliega junto al DLL del plugin (VST2/VST folder) para que
# Classifier.h lo encuentre via GetModuleFileNameA del propio plugin.
add_executable(WarzoneHelper WIN32
    Source/WarzoneHelper.cpp
)

target_include_directories(WarzoneHelper PRIVATE
    ${ORT_DIR}/include
)

target_link_libraries(WarzoneHelper PRIVATE
    ${ORT_DIR}/lib/onnxruntime.lib
)

if(MSVC)
    target_compile_options(WarzoneHelper PRIVATE /EHa /MT)
endif()

# Copiar WarzoneHelper.exe al mismo folder que el plugin VST2
add_custom_command(TARGET WarzoneHelper POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "$<TARGET_FILE:WarzoneHelper>"
        "${CMAKE_BINARY_DIR}/WarzoneProcessor_artefacts/$<CONFIG>/VST/"
    COMMENT "Copying WarzoneHelper.exe to VST2 output folder"
)
