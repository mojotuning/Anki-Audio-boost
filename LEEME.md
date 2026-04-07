# 🎮 WARZONE AUDIO ENHANCER
**Motor de audio inteligente con ML — Sin modificar el juego**

---

## ¿Qué hace esto?
- Captura el audio del sistema en tiempo real (lo que suena en tus auriculares)
- Amplifica pasos enemigos (frecuencias 80–600 Hz)
- Silencia tus propios pasos
- Amplifica disparos y ataques aéreos
- Aprende a diferenciar sonidos propios vs enemigos con Machine Learning

---

## PASO 1 — Instalar VB-Cable (loopback de audio)
Esto crea un dispositivo virtual que captura el audio del sistema.

1. Descarga **VB-CABLE** gratis: https://vb-audio.com/Cable/
2. Instálalo y reinicia el PC
3. En Windows: Ve a **Sonido > Reproducción** y pon "CABLE Input" como dispositivo predeterminado
4. Tus auriculares/bocinas se escuchan a través de VB-Cable

---

## PASO 2 — Instalar dependencias Python

Abre una terminal en la carpeta del proyecto y ejecuta:

```bash
pip install -r requirements.txt
```

Si tienes problemas con `librosa`:
```bash
pip install librosa --no-deps
pip install audioread decorator resampy
```

---

## PASO 3 — Iniciar el servidor

```bash
python server.py
```

Verás: `🎮 Warzone Audio Server iniciando en http://localhost:5000`

---

## PASO 4 — Abrir la interfaz

Abre el archivo `index.html` en tu navegador (Chrome recomendado).

---

## PASO 5 — Configurar dispositivos en la UI

| Campo   | Qué seleccionar                              |
|---------|----------------------------------------------|
| INPUT   | **CABLE Output** (VB-Cable) — captura el audio del sistema |
| OUTPUT  | Tus **auriculares** o bocinas                |

Presiona **▶ ACTIVAR**

---

## PASO 6 — Entrenar el modelo ML

1. Inicia una partida de Warzone
2. Cuando **TÚ** estés corriendo/caminando → presiona **"Mis Pasos"** en la UI
3. Cuando escuches **pasos de enemigos** → presiona **"Enemigo"** en la UI
4. Repite 10–20 veces cada uno
5. Presiona **"⚡ ENTRENAR AHORA"**

A partir de ese momento el modelo clasifica automáticamente y aplica los filtros.

---

## Configuración de ganancias recomendada

| Control           | Valor inicial | Ajusta según...                    |
|-------------------|---------------|------------------------------------|
| Pasos Enemigos    | 3.0×          | Sube si no escuchas bien los pasos |
| Pasos Propios     | 0.1×          | Baja más si te molestan los tuyos  |
| Disparos Enemigos | 2.0×          | Sube para ubicar la dirección      |
| Ataques Aéreos    | 2.5×          | Sube para anticipar killstreaks    |

---

## Notas importantes

- **Latencia**: Está configurada en modo `low`. En PCs lentas puede haber un pequeño delay (~20ms).
- **El modelo mejora con el tiempo**: Cuantas más muestras etiquetes, mejor diferencia.
- **Nada modifica el juego**: Solo procesa el audio de salida de Windows.
- **Compatibilidad**: Windows 10/11, Python 3.9+

---

## Solución de problemas

| Problema | Solución |
|----------|----------|
| No hay audio | Verifica que VB-Cable está como dispositivo predeterminado |
| Error de dispositivo | Reinicia el servidor y recarga la página |
| Modelo no entrena | Necesitas al menos 5 muestras de cada tipo |
| Mucha latencia | Reduce `BLOCK_SIZE` a 512 en `audio_engine.py` |
