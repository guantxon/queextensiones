import json
from pathlib import Path

workflow = {
    "name": "Agente IA Presupuestos y Valoraciones",
    "nodes": [],
    "connections": {},
    "pinData": {},
    "active": False,
    "settings": {
        "executionOrder": "v1",
        "saveManualExecutions": True
    },
    "versionId": "e2c96c2f-01af-4b3d-8b7a-56439025cae4"
}

nodes = workflow["nodes"]
connections = workflow["connections"]


def add_node(node):
    nodes.append(node)


def connect(source, output_index, target):
    conn = connections.setdefault(source, {"main": []})
    while len(conn["main"]) <= output_index:
        conn["main"].append([])
    conn["main"][output_index].append({"node": target, "type": "main", "index": 0})


def function_node(node_id, name, code, position):
    return {
        "parameters": {
            "functionCode": code
        },
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.function",
        "typeVersion": 1,
        "position": position
    }


add_node({
    "parameters": {
        "updates": ["messages"],
        "options": {}
    },
    "id": "trigger",
    "name": "WhatsApp Trigger",
    "type": "n8n-nodes-base.whatsAppTrigger",
    "typeVersion": 1,
    "position": [-1380, 420],
    "webhookId": "TRIGGER-UUID-REPLACE",
    "credentials": {
        "whatsAppTriggerApi": {
            "id": "l1oZAIL6uFnIFVcq",
            "name": "Plataformas Network"
        }
    }
})

add_node({
    "parameters": {
        "operation": "get",
        "key": "={{ 'session:' + ($json.messages?.[0]?.from || $json.body?.from || $json.from || $json.phone) }}"
    },
    "id": "redis_get",
    "name": "Cargar estado",
    "type": "n8n-nodes-base.redis",
    "typeVersion": 1,
    "position": [-1120, 420],
    "credentials": {
        "redis": {
            "id": "uUALR6mzUYb59fEr",
            "name": "Redis account"
        }
    }
})

init_code = """
const incoming = $json.messages?.[0] || $json;
const text = incoming?.text?.body || incoming?.message || incoming?.body || '';
const from = incoming?.from || incoming?.phone || incoming?.waId || incoming?.sender || 'desconocido';
let parsedState = {};
if ($json.value) {
  try {
    parsedState = JSON.parse($json.value);
  } catch (error) {
    parsedState = {};
  }
}
if (!parsedState.id) {
  parsedState = {
    id: from,
    stage: 'idle',
    userPhone: from,
    history: [],
    property: {},
    valuation: { pricePerSqm: 150, accepted: false, generated: false },
    budget: { requested: false, generated: false },
    facades: {},
    patios: {},
    roof: {},
    pendingAttachments: [],
    notes: [],
    vectorSummary: '',
    lastPlanner: null,
    pendingPrompts: []
  };
}
parsedState.history = parsedState.history || [];
parsedState.pendingAttachments = parsedState.pendingAttachments || [];
parsedState.notes = parsedState.notes || [];
parsedState.pendingPrompts = parsedState.pendingPrompts || [];
return [{ json: { incoming, messageText: text.trim(), state: parsedState } }];
"""
add_node(function_node("initialize_state", "Inicializar estado", init_code, [-930, 420]))

append_history_code = """
const state = $json.state;
const messageText = $json.messageText;
const timestamp = new Date().toISOString();
state.history.push({ role: 'user', content: messageText, ts: timestamp });
state.history = state.history.slice(-40);
$json.state = state;
return [{ json: $json }];
"""
add_node(function_node("append_history", "Anotar mensaje usuario", append_history_code, [-740, 420]))

planner_instructions = """Eres un asistente experto para rehabilitaciones de fachada y cubiertas que opera dentro de n8n.\nTu objetivo es guiar al usuario por el siguiente flujo de negocio:\n1. Detectar si el usuario desea iniciar un presupuesto/valoración. Si no, responde cordialmente y mantente a la espera.\n2. Solicitar la dirección completa y validar que dispone de datos catastrales. Cuando la dirección esté disponible, ordena que se lance la acción FETCH_CADASTRE con el campo address.\n3. Una vez recibidos perímetro, área, número de vecinos, locales y alturas, confirma con el usuario la información resumida. Si hay discrepancias, vuelve a pedir los datos.\n4. Propón una valoración inicial a 150 €/m² (o al precio indicado por el usuario). Permite modificar el precio detectando frases como \"cámbiame la repercusión por 160€ por metro cuadrado\" y actualiza pricePerSqm.\n5. Si el usuario acepta la valoración, ordena crear/actualizar una oportunidad en Odoo (acción UPSERT_OPPORTUNITY) con los datos recogidos y, a continuación, lanzar la acción GENERATE_VALUATION.\n6. Tras generar la valoración, solicita recuperar el adjunto PDF correspondiente (acción FETCH_VALUATION_ATTACHMENT) y programa su envío al usuario.\n7. Pregunta si desea continuar con el presupuesto. Si acepta, guía la recogida de datos por fachada siguiendo este orden: fachada principal, laterales, posterior, patios y cubierta.\n8. Para cada fachada recopila: nº plantas, altura estándar (3m salvo planta baja 3.5m), si planta baja lleva SATE, medidas (longitud, altura), detalles de terrazas, ventanas, vierteaguas, elementos singulares (aires, antenas, tuberías, toldos, rejas, etc.). Para patios y cubierta pide la información específica descrita en la guía de negocio.\n9. Permite que el usuario aporte fotos; registra las URL o IDs en el estado dentro de facades[clave].photos.\n10. Cuando todos los datos estén completos y el usuario confirme, ordena GENERATE_BUDGET y después FETCH_BUDGET_ATTACHMENT para devolver el PDF final.\n\nInstrucciones adicionales:\n- Mantén el estado sincronizado. Guarda los datos nuevos en el objeto state.* correspondiente.\n- Devuelve SIEMPRE una respuesta JSON válida con el siguiente formato (sin texto adicional):\n{\n  \"state\": { ... campos a fusionar ... },\n  \"actions\": [\n    {\"type\": \"FETCH_CADASTRE\", \"address\": \"...\"},\n    {\"type\": \"UPSERT_OPPORTUNITY\"},\n    {\"type\": \"GENERATE_VALUATION\"},\n    {\"type\": \"FETCH_VALUATION_ATTACHMENT\"},\n    {\"type\": \"GENERATE_BUDGET\"},\n    {\"type\": \"FETCH_BUDGET_ATTACHMENT\"}\n  ],\n  \"notes\": [\"mensaje interno opcional\"],\n  \"vectorSummary\": \"Resumen breve para almacenar en vector store\",\n  \"nextPrompts\": [\"preguntas o recordatorios para el agente de respuesta\"],\n  \"pendingAttachments\": [\"valuation_pdf\", \"budget_pdf\", ...]\n}\n- Incluye únicamente las acciones necesarias en este turno.\n- No generes attachments hasta que el usuario confirme.\n- Resume en vectorSummary lo más relevante del turno (<=280 caracteres)."""

build_planner_code = """
const state = $json.state;
const history = state.history || [];
const conversation = history.slice(-12).map(entry => `${entry.role.toUpperCase()}: ${entry.content}`).join('\\n');
const payload = {
  system: __PLANNER__,
  state,
  conversation,
  userMessage: $json.messageText
};
return [{ json: { ...$json, plannerPayload: payload } }];
""".replace("__PLANNER__", json.dumps(planner_instructions))
add_node(function_node("build_planner_prompt", "Construir prompt planificador", build_planner_code, [-540, 420]))

add_node({
    "parameters": {
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "googleGeminiApi",
        "method": "POST",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ { 'contents': [ { 'role': 'user', 'parts': [ { 'text': $json.plannerPayload.system + '\\n\\nESTADO ACTUAL:\\n' + JSON.stringify($json.plannerPayload.state) + '\\n\\nCONVERSACIÓN RECIENTE:\\n' + $json.plannerPayload.conversation + '\\n\\nMENSAJE USUARIO:\\n' + $json.plannerPayload.userMessage + '\\n\\nRESPONDE SOLO CON JSON VÁLIDO.' } ] } ] } }}",
        "options": {
            "queryParametersUi": {
                "parameter": [
                    {"name": "key", "value": "={{$credentials.apiKey}}"}
                ]
            }
        }
    },
    "id": "gemini_planner",
    "name": "Gemini Planificador",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 3,
    "position": [-330, 420],
    "credentials": {
        "googleGeminiApi": {
            "id": "IjZslc5BlrXiU9e5",
            "name": "Gemini API"
        }
    }
})

parse_planner_code = """
const raw = $json.candidates?.[0]?.content?.parts?.[0]?.text || '';
let parsed;
try {
  parsed = JSON.parse(raw);
} catch (error) {
  parsed = {
    state: {},
    actions: [],
    notes: ['Fallo al parsear respuesta de Gemini', error.message],
    vectorSummary: raw.slice(0, 200)
  };
}
if (!Array.isArray(parsed.actions)) {
  parsed.actions = [];
}
if (!Array.isArray(parsed.notes)) {
  parsed.notes = [];
}
if (!Array.isArray(parsed.pendingAttachments)) {
  parsed.pendingAttachments = [];
}
if (!Array.isArray(parsed.nextPrompts)) {
  parsed.nextPrompts = [];
}
const mergedState = { ...$json.state, ...(parsed.state || {}) };
mergedState.pendingAttachments = Array.from(new Set([...(mergedState.pendingAttachments || []), ...(parsed.pendingAttachments || [])]));
mergedState.notes = [...(mergedState.notes || []), ...parsed.notes.filter(n => !!n)];
mergedState.pendingPrompts = parsed.nextPrompts || [];
return [{ json: { ...$json, plan: parsed, actions: parsed.actions, state: mergedState } }];
"""
add_node(function_node("parse_planner", "Interpretar plan", parse_planner_code, [-120, 420]))

apply_plan_code = """
const state = $json.state;
state.lastPlanner = { ts: new Date().toISOString(), actions: $json.actions };
state.vectorSummary = $json.plan.vectorSummary || state.vectorSummary || '';
return [{ json: { ...$json, state } }];
"""
add_node(function_node("apply_plan", "Aplicar plan", apply_plan_code, [70, 420]))

add_node({
    "parameters": {
        "conditions": {
            "string": [
                {
                    "value1": "={{ $json.actions.find(action => action.type === 'FETCH_CADASTRE')?.address || '' }}",
                    "operation": "isEmpty"
                }
            ]
        }
    },
    "id": "if_cadastre",
    "name": "¿Buscar datos catastrales?",
    "type": "n8n-nodes-base.if",
    "typeVersion": 1,
    "position": [260, 420]
})

add_node({
    "parameters": {
        "authentication": "none",
        "method": "GET",
        "url": "https://api.plataformas.network/cadastre",
        "options": {
            "queryParametersUi": {
                "parameter": [
                    {"name": "address", "value": "={{ $json.actions.find(action => action.type === 'FETCH_CADASTRE').address }}"}
                ]
            }
        }
    },
    "id": "catastro_request",
    "name": "Catastro API",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 3,
    "position": [470, 320]
})

merge_catastro_code = """
const response = $json;
const upstream = $items('Aplicar plan')[0].json;
const state = upstream.state;
const action = upstream.actions.find(action => action.type === 'FETCH_CADASTRE') || {};
state.property = {
  ...(state.property || {}),
  fetchedAt: new Date().toISOString(),
  source: 'catastro',
  raw: response,
  perimeter: response.perimeter || state.property?.perimeter || null,
  area: response.area || state.property?.area || null,
  neighbours: response.neighbours || response.neighbors || state.property?.neighbours || null,
  locals: response.locals || response.shops || state.property?.locals || 0,
  heights: response.heights || response.floors || state.property?.heights || null,
  address: response.address || action.address || state.property?.address
};
return [{ json: { ...upstream, state } }];
"""
add_node(function_node("merge_catastro", "Incorporar catastro", merge_catastro_code, [680, 320]))

add_node({
    "parameters": {
        "conditions": {
            "string": [
                {
                    "value1": "={{ $json.actions.find(action => action.type === 'UPSERT_OPPORTUNITY') ? 'yes' : '' }}",
                    "operation": "isEmpty"
                }
            ]
        }
    },
    "id": "if_opportunity",
    "name": "¿Crear oportunidad?",
    "type": "n8n-nodes-base.if",
    "typeVersion": 1,
    "position": [880, 420]
})

add_node({
    "parameters": {
        "resource": "lead",
        "operation": "createOrUpdate",
        "domain": "={{ $json.state.odoo?.domain || [] }}",
        "updateFields": {
            "name": "={{ 'Rehabilitación ' + ($json.state.property?.address || 'sin dirección') }}",
            "phone": "={{ $json.state.userPhone }}",
            "street": "={{ $json.state.property?.address || '' }}",
            "expectedRevenue": "={{ $json.state.property?.area ? ($json.state.property.area * ($json.state.valuation?.pricePerSqm || 150)) : undefined }}",
            "probability": 30,
            "description": "={{ JSON.stringify({ property: $json.state.property, valuation: $json.state.valuation, facades: $json.state.facades, patios: $json.state.patios, roof: $json.state.roof }, null, 2) }}"
        }
    },
    "id": "odoo_opportunity",
    "name": "Odoo oportunidad",
    "type": "n8n-nodes-base.odoo",
    "typeVersion": 1,
    "position": [1090, 320],
    "credentials": {
        "odooApi": {
            "id": "4X2L1nT8bQ4gkR9d",
            "name": "Plataformas Odoo"
        }
    }
})

merge_opportunity_code = """
const upstream = $items('¿Crear oportunidad?')[0].json;
const state = upstream.state;
const result = $json;
state.odoo = state.odoo || {};
state.odoo.opportunityId = result.id || result[0]?.id || state.odoo.opportunityId || null;
state.odoo.lastSync = new Date().toISOString();
return [{ json: { ...upstream, state } }];
"""
add_node(function_node("merge_opportunity", "Guardar oportunidad", merge_opportunity_code, [1300, 320]))

add_node({
    "parameters": {
        "conditions": {
            "string": [
                {
                    "value1": "={{ $json.actions.find(action => action.type === 'GENERATE_VALUATION') ? 'yes' : '' }}",
                    "operation": "isEmpty"
                }
            ]
        }
    },
    "id": "if_generate_valuation",
    "name": "¿Generar valoración?",
    "type": "n8n-nodes-base.if",
    "typeVersion": 1,
    "position": [1500, 420]
})

add_node({
    "parameters": {
        "resource": "lead",
        "operation": "executeAction",
        "leadId": "={{ $json.state.odoo?.opportunityId }}",
        "action": "action_generate_valuation"
    },
    "id": "odoo_generate_valuation",
    "name": "Odoo generar valoración",
    "type": "n8n-nodes-base.odoo",
    "typeVersion": 1,
    "position": [1700, 320],
    "credentials": {
        "odooApi": {
            "id": "4X2L1nT8bQ4gkR9d",
            "name": "Plataformas Odoo"
        }
    }
})

mark_valuation_code = """
const upstream = $items('¿Generar valoración?')[0].json;
const state = upstream.state;
state.valuation = state.valuation || {};
state.valuation.generated = true;
state.valuation.generatedAt = new Date().toISOString();
return [{ json: { ...upstream, state } }];
"""
add_node(function_node("mark_valuation", "Marcar valoración", mark_valuation_code, [1900, 320]))

add_node({
    "parameters": {
        "conditions": {
            "string": [
                {
                    "value1": "={{ $json.actions.find(action => action.type === 'FETCH_VALUATION_ATTACHMENT') ? 'yes' : '' }}",
                    "operation": "isEmpty"
                }
            ]
        }
    },
    "id": "if_fetch_valuation",
    "name": "¿Recuperar valoración?",
    "type": "n8n-nodes-base.if",
    "typeVersion": 1,
    "position": [2100, 420]
})

add_node({
    "parameters": {
        "resource": "lead",
        "operation": "getAttachments",
        "leadId": "={{ $json.state.odoo?.opportunityId }}",
        "options": {
            "filters": "name ilike 'valoracion'"
        }
    },
    "id": "odoo_fetch_valuation",
    "name": "Odoo adjunto valoración",
    "type": "n8n-nodes-base.odoo",
    "typeVersion": 1,
    "position": [2300, 320],
    "credentials": {
        "odooApi": {
            "id": "4X2L1nT8bQ4gkR9d",
            "name": "Plataformas Odoo"
        }
    }
})

prepare_valuation_attachment_code = """
const upstream = $items('¿Recuperar valoración?')[0].json;
const state = upstream.state;
const attachments = Array.isArray($json) ? $json : ($json.attachments || []);
if (!state.pendingAttachments.includes('valuation_pdf')) {
  state.pendingAttachments.push('valuation_pdf');
}
state.valuation = state.valuation || {};
state.valuation.attachment = attachments[0] || attachments;
return [{ json: { ...upstream, state, valuationAttachment: attachments[0] || null } }];
"""
add_node(function_node("prepare_valuation_attachment", "Preparar adjunto valoración", prepare_valuation_attachment_code, [2500, 320]))

add_node({
    "parameters": {
        "conditions": {
            "string": [
                {
                    "value1": "={{ $json.actions.find(action => action.type === 'GENERATE_BUDGET') ? 'yes' : '' }}",
                    "operation": "isEmpty"
                }
            ]
        }
    },
    "id": "if_generate_budget",
    "name": "¿Generar presupuesto?",
    "type": "n8n-nodes-base.if",
    "typeVersion": 1,
    "position": [2700, 420]
})

add_node({
    "parameters": {
        "resource": "lead",
        "operation": "executeAction",
        "leadId": "={{ $json.state.odoo?.opportunityId }}",
        "action": "action_generate_budget"
    },
    "id": "odoo_generate_budget",
    "name": "Odoo generar presupuesto",
    "type": "n8n-nodes-base.odoo",
    "typeVersion": 1,
    "position": [2900, 320],
    "credentials": {
        "odooApi": {
            "id": "4X2L1nT8bQ4gkR9d",
            "name": "Plataformas Odoo"
        }
    }
})

mark_budget_code = """
const upstream = $items('¿Generar presupuesto?')[0].json;
const state = upstream.state;
state.budget = state.budget || {};
state.budget.generated = true;
state.budget.generatedAt = new Date().toISOString();
return [{ json: { ...upstream, state } }];
"""
add_node(function_node("mark_budget", "Marcar presupuesto", mark_budget_code, [3100, 320]))

add_node({
    "parameters": {
        "conditions": {
            "string": [
                {
                    "value1": "={{ $json.actions.find(action => action.type === 'FETCH_BUDGET_ATTACHMENT') ? 'yes' : '' }}",
                    "operation": "isEmpty"
                }
            ]
        }
    },
    "id": "if_fetch_budget",
    "name": "¿Recuperar presupuesto?",
    "type": "n8n-nodes-base.if",
    "typeVersion": 1,
    "position": [3300, 420]
})

add_node({
    "parameters": {
        "resource": "lead",
        "operation": "getAttachments",
        "leadId": "={{ $json.state.odoo?.opportunityId }}",
        "options": {
            "filters": "name ilike 'presupuesto'"
        }
    },
    "id": "odoo_fetch_budget",
    "name": "Odoo adjunto presupuesto",
    "type": "n8n-nodes-base.odoo",
    "typeVersion": 1,
    "position": [3500, 320],
    "credentials": {
        "odooApi": {
            "id": "4X2L1nT8bQ4gkR9d",
            "name": "Plataformas Odoo"
        }
    }
})

prepare_budget_attachment_code = """
const upstream = $items('¿Recuperar presupuesto?')[0].json;
const state = upstream.state;
const attachments = Array.isArray($json) ? $json : ($json.attachments || []);
if (!state.pendingAttachments.includes('budget_pdf')) {
  state.pendingAttachments.push('budget_pdf');
}
state.budget = state.budget || {};
state.budget.attachment = attachments[0] || attachments;
return [{ json: { ...upstream, state, budgetAttachment: attachments[0] || null } }];
"""
add_node(function_node("prepare_budget_attachment", "Preparar adjunto presupuesto", prepare_budget_attachment_code, [3700, 320]))

responder_instructions = "Actúa como asistente de presupuestos de rehabilitación. Redacta respuestas claras, enumera datos importantes y confirma próximos pasos. Si hay preguntas pendientes en state.pendingPrompts, respóndelas o preséntalas al usuario. Menciona cuando se adjunta un PDF. Usa un tono profesional y cercano."

prepare_responder_code = """
const state = $json.state;
const history = state.history || [];
const conversation = history.slice(-12).map(entry => `${entry.role.toUpperCase()}: ${entry.content}`).join('\\n');
const prompt = __RESPONDER__ + '\n\nRESUMEN VECTOR: ' + (state.vectorSummary || '') + '\n\nESTADO:\n' + JSON.stringify(state) + '\n\nCONVERSACIÓN RECIENTE:\n' + conversation + '\n\nRedacta la respuesta final en español.';
return [{ json: { ...$json, responderPrompt: prompt } }];
""".replace("__RESPONDER__", json.dumps(responder_instructions))
add_node(function_node("prepare_responder_prompt", "Construir prompt respuesta", prepare_responder_code, [3900, 420]))

add_node({
    "parameters": {
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "googleGeminiApi",
        "method": "POST",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ { 'contents': [ { 'role': 'user', 'parts': [ { 'text': $json.responderPrompt } ] } ] } }}",
        "options": {
            "queryParametersUi": {
                "parameter": [
                    {"name": "key", "value": "={{$credentials.apiKey}}"}
                ]
            }
        }
    },
    "id": "gemini_responder",
    "name": "Gemini Respuesta",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 3,
    "position": [4100, 420],
    "credentials": {
        "googleGeminiApi": {
            "id": "IjZslc5BlrXiU9e5",
            "name": "Gemini API"
        }
    }
})

finalize_response_code = """
const state = $json.state;
const reply = $json.candidates?.[0]?.content?.parts?.map(p => p.text).join('\n').trim() || 'He recibido tu mensaje.';
state.history.push({ role: 'assistant', content: reply, ts: new Date().toISOString() });
state.history = state.history.slice(-40);
$json.state = state;
$json.reply = reply;
return [{ json: $json }];
"""
add_node(function_node("finalize_response", "Finalizar respuesta", finalize_response_code, [4300, 420]))

add_node({
    "parameters": {
        "operation": "set",
        "key": "={{ 'session:' + $json.state.userPhone }}",
        "value": "={{ JSON.stringify($json.state) }}",
        "expire": 86400
    },
    "id": "redis_set",
    "name": "Guardar estado",
    "type": "n8n-nodes-base.redis",
    "typeVersion": 1,
    "position": [4500, 420],
    "credentials": {
        "redis": {
            "id": "uUALR6mzUYb59fEr",
            "name": "Redis account"
        }
    }
})

prepare_vector_code = """
const text = `${$json.state.userPhone} | ${new Date().toISOString()}\nUsuario: ${$json.messageText}\nAsistente: ${$json.reply}\nResumen: ${$json.state.vectorSummary || ''}`;
return [{ json: { ...$json, vectorText: text } }];
"""
add_node(function_node("prepare_vector", "Preparar vector", prepare_vector_code, [4700, 420]))

add_node({
    "parameters": {
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "googleGeminiApi",
        "method": "POST",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/embedding-001:embedContent",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ { 'content': { 'parts': [ { 'text': $json.vectorText } ] } } }}",
        "options": {
            "queryParametersUi": {
                "parameter": [
                    {"name": "key", "value": "={{$credentials.apiKey}}"}
                ]
            }
        }
    },
    "id": "gemini_embeddings",
    "name": "Gemini Embeddings",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 3,
    "position": [4900, 420],
    "credentials": {
        "googleGeminiApi": {
            "id": "IjZslc5BlrXiU9e5",
            "name": "Gemini API"
        }
    }
})

add_node({
    "parameters": {
        "operation": "upsert",
        "vectorStoreId": "presupuestos-memory",
        "text": "={{ $json.vectorText }}",
        "embedding": "={{ $json.embedding?.values || $json.candidates?.[0]?.embedding?.values }}",
        "metadata": "={{ { stage: $json.state.stage, phone: $json.state.userPhone, timestamp: new Date().toISOString() } }}"
    },
    "id": "vector_upsert",
    "name": "Vector Store Upsert",
    "type": "n8n-nodes-base.vectorStore",
    "typeVersion": 1,
    "position": [5100, 420],
    "credentials": {
        "vectorStore": {
            "id": "Dz7cMaYxq2pWXm1f",
            "name": "Basic Vector Store"
        }
    }
})

add_node({
    "parameters": {
        "resource": "message",
        "operation": "send",
        "recipientType": "individual",
        "to": "={{ $json.state.userPhone }}",
        "type": "text",
        "text": {
            "body": "={{ $json.reply }}"
        }
    },
    "id": "whatsapp_send",
    "name": "Enviar WhatsApp",
    "type": "n8n-nodes-base.whatsApp",
    "typeVersion": 1,
    "position": [5300, 420],
    "credentials": {
        "whatsAppApi": {
            "id": "7vQ58WfC1m3r9dL0",
            "name": "Plataformas Network"
        }
    }
})

add_node({
    "parameters": {
        "conditions": {
            "string": [
                {
                    "value1": "={{ $json.state.pendingAttachments.includes('valuation_pdf') ? 'yes' : '' }}",
                    "operation": "isEmpty"
                }
            ]
        }
    },
    "id": "if_send_valuation",
    "name": "¿Enviar valoración?",
    "type": "n8n-nodes-base.if",
    "typeVersion": 1,
    "position": [5500, 420]
})

valuation_binary_code = """
const attachment = $json.valuationAttachment || $json.state.valuation?.attachment;
if (!attachment) {
  return [{ json: $json }];
}
const data = attachment.datas || attachment.data || attachment.base64 || null;
if (data) {
  const buffer = Buffer.from(data, 'base64');
  $item(0).binary = $item(0).binary || {};
  $item(0).binary.valuation = {
    data: buffer.toString('base64'),
    mimeType: attachment.mimetype || 'application/pdf',
    fileName: attachment.name || 'valoracion.pdf'
  };
}
return [{ json: $json, binary: $item(0).binary }];
"""
add_node(function_node("prepare_valuation_binary", "Preparar PDF valoración", valuation_binary_code, [5700, 320]))

add_node({
    "parameters": {
        "resource": "message",
        "operation": "send",
        "recipientType": "individual",
        "to": "={{ $json.state.userPhone }}",
        "type": "document",
        "document": {
            "binaryPropertyName": "valuation",
            "caption": "Valoración inicial"
        }
    },
    "id": "whatsapp_send_valuation",
    "name": "Enviar valoración",
    "type": "n8n-nodes-base.whatsApp",
    "typeVersion": 1,
    "position": [5900, 320],
    "credentials": {
        "whatsAppApi": {
            "id": "7vQ58WfC1m3r9dL0",
            "name": "Plataformas Network"
        }
    }
})

add_node({
    "parameters": {
        "conditions": {
            "string": [
                {
                    "value1": "={{ $json.state.pendingAttachments.includes('budget_pdf') ? 'yes' : '' }}",
                    "operation": "isEmpty"
                }
            ]
        }
    },
    "id": "if_send_budget",
    "name": "¿Enviar presupuesto?",
    "type": "n8n-nodes-base.if",
    "typeVersion": 1,
    "position": [5500, 660]
})

budget_binary_code = """
const attachment = $json.budgetAttachment || $json.state.budget?.attachment;
if (!attachment) {
  return [{ json: $json }];
}
const data = attachment.datas || attachment.data || attachment.base64 || null;
if (data) {
  const buffer = Buffer.from(data, 'base64');
  $item(0).binary = $item(0).binary || {};
  $item(0).binary.budget = {
    data: buffer.toString('base64'),
    mimeType: attachment.mimetype || 'application/pdf',
    fileName: attachment.name || 'presupuesto.pdf'
  };
}
return [{ json: $json, binary: $item(0).binary }];
"""
add_node(function_node("prepare_budget_binary", "Preparar PDF presupuesto", budget_binary_code, [5700, 560]))

add_node({
    "parameters": {
        "resource": "message",
        "operation": "send",
        "recipientType": "individual",
        "to": "={{ $json.state.userPhone }}",
        "type": "document",
        "document": {
            "binaryPropertyName": "budget",
            "caption": "Presupuesto de rehabilitación"
        }
    },
    "id": "whatsapp_send_budget",
    "name": "Enviar presupuesto",
    "type": "n8n-nodes-base.whatsApp",
    "typeVersion": 1,
    "position": [5900, 560],
    "credentials": {
        "whatsAppApi": {
            "id": "7vQ58WfC1m3r9dL0",
            "name": "Plataformas Network"
        }
    }
})

connect("WhatsApp Trigger", 0, "Cargar estado")
connect("Cargar estado", 0, "Inicializar estado")
connect("Inicializar estado", 0, "Anotar mensaje usuario")
connect("Anotar mensaje usuario", 0, "Construir prompt planificador")
connect("Construir prompt planificador", 0, "Gemini Planificador")
connect("Gemini Planificador", 0, "Interpretar plan")
connect("Interpretar plan", 0, "Aplicar plan")
connect("Aplicar plan", 0, "¿Buscar datos catastrales?")
connect("¿Buscar datos catastrales?", 0, "¿Crear oportunidad?")
connect("¿Buscar datos catastrales?", 1, "Catastro API")
connect("Catastro API", 0, "Incorporar catastro")
connect("Incorporar catastro", 0, "¿Crear oportunidad?")
connect("¿Crear oportunidad?", 0, "¿Generar valoración?")
connect("¿Crear oportunidad?", 1, "Odoo oportunidad")
connect("Odoo oportunidad", 0, "Guardar oportunidad")
connect("Guardar oportunidad", 0, "¿Generar valoración?")
connect("¿Generar valoración?", 0, "¿Recuperar valoración?")
connect("¿Generar valoración?", 1, "Odoo generar valoración")
connect("Odoo generar valoración", 0, "Marcar valoración")
connect("Marcar valoración", 0, "¿Recuperar valoración?")
connect("¿Recuperar valoración?", 0, "¿Generar presupuesto?")
connect("¿Recuperar valoración?", 1, "Odoo adjunto valoración")
connect("Odoo adjunto valoración", 0, "Preparar adjunto valoración")
connect("Preparar adjunto valoración", 0, "¿Generar presupuesto?")
connect("¿Generar presupuesto?", 0, "¿Recuperar presupuesto?")
connect("¿Generar presupuesto?", 1, "Odoo generar presupuesto")
connect("Odoo generar presupuesto", 0, "Marcar presupuesto")
connect("Marcar presupuesto", 0, "¿Recuperar presupuesto?")
connect("¿Recuperar presupuesto?", 0, "Construir prompt respuesta")
connect("¿Recuperar presupuesto?", 1, "Odoo adjunto presupuesto")
connect("Odoo adjunto presupuesto", 0, "Preparar adjunto presupuesto")
connect("Preparar adjunto presupuesto", 0, "Construir prompt respuesta")
connect("Construir prompt respuesta", 0, "Gemini Respuesta")
connect("Gemini Respuesta", 0, "Finalizar respuesta")
connect("Finalizar respuesta", 0, "Guardar estado")
connect("Guardar estado", 0, "Preparar vector")
connect("Preparar vector", 0, "Gemini Embeddings")
connect("Gemini Embeddings", 0, "Vector Store Upsert")
connect("Vector Store Upsert", 0, "Enviar WhatsApp")
connect("Enviar WhatsApp", 0, "¿Enviar valoración?")
connect("¿Enviar valoración?", 0, "¿Enviar presupuesto?")
connect("¿Enviar valoración?", 1, "Preparar PDF valoración")
connect("Preparar PDF valoración", 0, "Enviar valoración")
connect("Enviar valoración", 0, "¿Enviar presupuesto?")
connect("¿Enviar presupuesto?", 1, "Preparar PDF presupuesto")
connect("Preparar PDF presupuesto", 0, "Enviar presupuesto")

Path('flows/presupuesto_valoracion_flow.json').write_text(json.dumps(workflow, indent=2, ensure_ascii=False))
