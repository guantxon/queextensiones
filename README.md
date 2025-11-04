# queextensiones

Tienda de extensiones de pelo natural https://queextensiones.com/

## Automatización de presupuestos y valoraciones

Se añadió un flujo de n8n en `flows/presupuesto_valoracion_flow.json` que arranca desde WhatsApp y mantiene el estado en Redis.
El agente guía al usuario paso a paso para completar los datos mínimos de una valoración (perímetro, superficie, alturas, vecinos y precio por metro cuadrado) o un presupuesto (incluyendo evidencias fotográficas). El estado de la conversación queda persistido para futuras consultas.

> ⚠️ Las llamadas reales a Catastro, análisis de visión y generación de PDF en Odoo están modeladas como placeholders dentro del nodo "Agente Maestro" y deben reemplazarse por integraciones reales según las credenciales disponibles.

## Router omnicanal por WhatsApp

El flujo `flows/main_router_whatsapp.json` replica la lógica del enrutador principal de Telegram, pero adaptado al canal de WhatsApp con botones interactivos para manejar los callbacks. Normaliza los mensajes entrantes del Cloud API (texto, audio, imágenes, documentos y ubicación), transcribe las notas de voz con Gemini, persiste el estado de la conversación en la Data Table `conversation_state` y reenvía cada interacción al webhook correspondiente según la categoría seleccionada.
