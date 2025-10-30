# queextensiones

Tienda de extensiones de pelo natural https://queextensiones.com/

## Automatización de presupuestos y valoraciones

Se añadió un flujo de n8n en `flows/presupuesto_valoracion_flow.json` que arranca desde WhatsApp y mantiene el estado en Redis. El agente guía al usuario paso a paso para completar los datos mínimos de una valoración (perímetro, superficie, alturas, vecinos y precio por metro cuadrado) o un presupuesto (incluyendo evidencias fotográficas). El estado de la conversación queda persistido para futuras consultas.

> ⚠️ Las llamadas reales a Catastro, análisis de visión y generación de PDF en Odoo están modeladas como placeholders dentro del nodo "Agente Maestro" y deben reemplazarse por integraciones reales según las credenciales disponibles.

## Consulta de datos catastrales por dirección
El flujo `flows/catastro_lookup_flow.json` expone un webhook HTTP (`POST /webhook/catastro-api`) que acepta direcciones libres, las normaliza y realiza geocodificación con Nominatim y Photon. Con las coordenadas obtenidas consulta los servicios públicos del Catastro español (RCCOOR, DNPRC, CPMRC, WMS/INSPIRE) para recuperar la referencia catastral, superficies, perímetros, alturas (calculadas o estimadas) y número de viviendas/locales.

La respuesta devuelta incluye tanto una estructura JSON como un mensaje en texto enriquecido con los datos más relevantes, además de metadatos sobre las fuentes utilizadas y enlaces a la ficha del inmueble en la sede electrónica del Catastro.

El flujo ahora utiliza los servicios WCF oficiales del Catastro (`OVCServWeb/OVCWcfCatastro/OVCCoordenadas.svc` y `OVCServWeb/OVCWcfCallejero/COVCCallejero.svc`) en lugar de los antiguos endpoints ASMX. Cada dato se recopila de forma incremental: primero se geocodifica la dirección, luego se consulta `Consulta_RCCOOR` para obtener referencias exactas por coordenadas y se amplía con `Consulta_RCCOOR_Distancia` o `Consulta_DNPPP` si es necesario. Con la referencia resultante se realizan peticiones consecutivas a `Consulta_CPMRC` y `Consulta_DNPRC` para enriquecer la respuesta con superficies, usos, alturas y metadatos oficiales antes de calcular geometrías y estimaciones adicionales.

