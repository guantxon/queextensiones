#!/bin/bash
# render_video.sh
# Script auxiliar invocado desde n8n para componer video final.
# Recibe como primer argumento la ruta a un archivo JSON con rutas temporales a assets.

set -euo pipefail

INPUT_PATH=${1:-}
if [[ -z "$INPUT_PATH" || ! -f "$INPUT_PATH" ]]; then
  echo "Debe proporcionar la ruta a un JSON de configuración" >&2
  exit 1
fi

python3 - "$INPUT_PATH" <<'PYTHON'
import json
import os
import subprocess
import sys
import textwrap

input_path = sys.argv[1]
with open(input_path, 'r', encoding='utf-8') as f:
    payload = json.load(f)

scenes = payload.get('scenes', [])
voice_over = payload.get('voiceOverPath')
music = payload.get('musicPath')
output = payload.get('outputPath', 'final_video.mp4')
workspace = payload.get('workspace') or os.path.dirname(output) or '.'
os.makedirs(workspace, exist_ok=True)

scene_files = []

for idx, scene in enumerate(sorted(scenes, key=lambda s: s.get('order', idx))):
    still = scene.get('imagePath')
    if not still or not os.path.exists(still):
        raise FileNotFoundError(f"Imagen de escena no encontrada: {still}")
    duration = float(scene.get('duration', 15))
    overlay_text = scene.get('overlayText', '')
    logo = scene.get('logoPath') if scene.get('logoPath') and os.path.exists(scene.get('logoPath')) else None
    avatar = scene.get('avatarPath') if scene.get('avatarPath') and os.path.exists(scene.get('avatarPath')) else None

    scene_output = os.path.join(workspace, f"scene_{idx:02d}.mp4")

    filter_parts = ["[0:v]scale=1920:1080,zoompan=z='min(zoom+0.002,1.05)':d=125:s=1920x1080:fps=25[base];"]
    last_label = '[base]'

    if logo:
        escaped_logo = logo.replace('\\', '\\\\').replace("'", "\\'")
        filter_parts.append(f"movie='{escaped_logo}'[logo];{last_label}[logo]overlay=W-w-80:80:enable='between(t,0,{duration})'[base_logo];")
        last_label = '[base_logo]'

    if avatar:
        escaped_avatar = avatar.replace('\\', '\\\\').replace("'", "\\'")
        filter_parts.append(f"movie='{escaped_avatar}'[avatar];{last_label}[avatar]overlay=80:80:enable='between(t,0,{duration})'[base_avatar];")
        last_label = '[base_avatar]'

    if overlay_text:
        text = overlay_text.replace('"', '\\"')
        filter_parts.append(textwrap.dedent(f"""
            {last_label}drawtext=text={text}:fontcolor=white:fontsize=48:x=(w-text_w)/2:y=h-160:borderw=2:bordercolor=0x000000@0.6[outv]
        """).strip())
        last_label = '[outv]'

    if last_label != '[outv]':
        filter_parts.append(f"{last_label}format=yuv420p[outv]")

    filter_complex = ''.join(filter_parts)

    cmd = [
        'ffmpeg','-y','-loop','1','-i', still,
        '-filter_complex', filter_complex,
        '-t', str(duration),
        '-pix_fmt', 'yuv420p',
        '-c:v', 'libx264',
        '-r', '25',
        scene_output
    ]

    subprocess.run(cmd, check=True)
    scene_files.append(scene_output)

if not scene_files:
    raise RuntimeError('No se generaron escenas')

concat_list = os.path.join(workspace, 'timeline.txt')
with open(concat_list, 'w', encoding='utf-8') as f:
    for path in scene_files:
        f.write(f"file '{path}'\n")

scene_video = os.path.join(workspace, 'scenes.mp4')
subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i', concat_list,'-c','copy', scene_video], check=True)

if not voice_over or not os.path.exists(voice_over):
    raise FileNotFoundError('No se encontró archivo de voz en off')

if not music or not os.path.exists(music):
    raise FileNotFoundError('No se encontró pista musical')

mixed_audio = os.path.join(workspace, 'mix.m4a')
subprocess.run([
    'ffmpeg','-y','-i', voice_over,'-i', music,
    '-filter_complex','[1:a]volume=0.35[a1];[a1][0:a]sidechaincompress=threshold=0.1:ratio=6:attack=5:release=250[bgmduck];[0:a][bgmduck]amix=inputs=2:weights=1 1:normalize=1[aout]',
    '-map','[aout]','-c:a','aac','-b:a','192k', mixed_audio
], check=True)

subprocess.run([
    'ffmpeg','-y','-i', scene_video,'-i', mixed_audio,
    '-c:v','libx264','-preset','medium','-crf','18',
    '-c:a','aac','-b:a','192k','-shortest', output
], check=True)

print(json.dumps({"videoPath": output}))
PYTHON
