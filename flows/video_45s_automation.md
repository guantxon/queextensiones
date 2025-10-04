# Flujo n8n: Formulario a video automatizado de 45 segundos

Este flujo de n8n recibe un guion, logo y avatar a través de un formulario público y devuelve un video de ~45 segundos con voz en off, música de fondo y escenas generadas automáticamente.

## Resumen de nodos y configuraciones

1. **Formulario Brief (`Form Trigger`)**
   - Endpoint: `/brief-video-45s`.
   - Campos: `script` (textarea), `logo` (archivo), `avatar` (archivo).
   - Define restricciones para formatos (PNG/SVG para logo y JPG/PNG para avatar).

2. **Normalizar Entradas (`Function`)**
   - Limpia el guion, fija duración objetivo (45 s) y conserva binarios de logo y avatar en propiedades `assets.logo` y `assets.avatar`.

3. **Storyboard IA (`OpenAI Chat`)**
   - Modelo `gpt-4.1-mini` con formato JSON.
   - Devuelve 3 escenas (~15 s cada una) con prompts visuales y texto para overlays mencionando logo/avatar cuando aplique.

4. **Expandir Escenas (`Function`)**
   - Convierte el JSON de escenas en items independientes con la metadata del guion y assets.

5. **Iterar Escenas (`SplitInBatches`)**
   - Itera cada escena individualmente para generar sus recursos visuales.

6. **Generar Imagen Escena (`HTTP Request` a OpenAI Images)**
   - Modelo `gpt-image-1`, tamaño 1792×1024.
   - Prompt: instrucciones del storyboard + recordatorio de espacio para logo/avatar.

7. **Decodificar Imagen (`Move Binary Data`)**
   - Convierte la respuesta Base64 a binario `sceneImage`.

8. **Preparar Payload Escena (`Function`)**
   - Calcula duración de escena, conserva overlay text e imagen.

9. **Unir Escenas (`Merge`)**
   - Recompila todos los items generados, manteniendo el orden según `scene.order`.

10. **Generar Voz en Off (`HTTP Request` a OpenAI TTS)**
    - Endpoint: `audio/speech` con modelo `gpt-4o-mini-tts`, voz `alloy`, salida MP3.

11. **Buscar Música (`HTTP Request` a Pixabay)**
    - Filtra por pistas corporativas de 40-60 s.

12. **Seleccionar Pista (`Function`)**
    - Toma la pista más popular y devuelve `downloadUrl`.

13. **Descargar Música (`HTTP Request`)**
    - Obtiene el archivo de audio en binario.

14. **Renderizar Video (`Execute Command`)**
    - Llama un script `scripts/render_video.sh` que usa FFmpeg.
    - El script debe: 
      1. Crear clips estáticos por escena aplicando efecto Ken Burns y duración exacta.
      2. Superponer logo (arriba derecha) y avatar (arriba izquierda o según escena) con transparencia animada.
      3. Añadir títulos/overlay text por escena con fuente corporativa.
      4. Sincronizar voz en off con escenas según `start/end`.
      5. Normalizar niveles de audio, reduciendo música al 30% (-10 dB) durante narración.
      6. Exportar a `final_video.mp4` (H.264 + AAC, 1920×1080, 25 fps).

15. **Entregar Video (`Respond to Webhook`)**
    - Devuelve el binario `video` generado por el script como respuesta HTTP (descarga).

## Recomendaciones de coherencia audiovisual

- **Control de duración:** Validar que la suma de duraciones por escena sea ≤ 45 s; si excede, ajustar la última escena mediante `Math.min` dentro del script de render.
- **Textos y brand assets:** Mantener logo en PNG con transparencia y avatar recortado en círculo dentro del script `render_video.sh` para evitar fondos duros.
- **Estrategia musical:** Fijar compresión side-chain en FFmpeg (`sidechaincompress`) para que la voz destaque sin perder presencia musical.
- **Gestión de voz:** Permitir parametrizar voz y tono desde campos opcionales del formulario si se requiere personalización.
- **Logs y reintentos:** Añadir nodos `Error Trigger` y `IF` para reintentos cuando los servicios externos fallen (OpenAI/Pixabay).
- **Entrega:** Considerar un nodo adicional `Email` o `Notion` para notificar al usuario con enlace al video alojado en S3 o similar, usando el mismo binario generado.

## Dependencias externas

- **OpenAI** (chat, imágenes, TTS) – requiere credenciales `OPENAI_API_KEY`.
- **Pixabay Audio API** – requiere `PIXABAY_API_KEY`.
- **FFmpeg** instalado en el host de n8n y script personalizado en `scripts/render_video.sh`.

## Script de render sugerido

```bash
#!/bin/bash
# scripts/render_video.sh
# Espera JSON por stdin (parámetros `$1`) con rutas temporales creadas por n8n.
# Se recomienda que n8n cree archivos temporales antes de invocar el script.

set -euo pipefail

# 1. Crear recursos temporales desde binarios
# 2. Generar timeline y filtros FFmpeg
# 3. Exportar final_video.mp4 y devolver ruta para que n8n lo lea
```

Ajusta el script según la infraestructura (docker, volumen compartido, etc.).
