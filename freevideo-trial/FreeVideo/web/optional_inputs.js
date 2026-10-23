// The optional advanced inputs were appended after the first public workflow
// shape. A workflow restored from an older version, or a widget list that moved,
// can leave an empty or missing value in them, and Comfy then rejects the whole
// request. Keep each of them to a value the server accepts.
const DEFAULTS = {continue_from: '', frames: 0, first_frame_reference: false};

export function optionalInputValue(name, value) {
    if (name === 'frames') return Number.isSafeInteger(value) && value >= 0 ? value : 0;
    if (name === 'continue_from') return typeof value === 'string' ? value : '';
    if (name === 'first_frame_reference') return value === true;
    return value;
}

export function cleanOptionalWidgets(node) {
    for (const widget of node?.widgets || []) {
        if (!(widget.name in DEFAULTS)) continue;
        const value = optionalInputValue(widget.name, widget.value);
        if (value !== widget.value) widget.value = value;
    }
}

export function cleanOptionalPrompt(prompt) {
    for (const entry of Object.values(prompt?.output || {})) {
        if (entry?.class_type !== 'FreeVideoGenerate' || !entry.inputs) continue;
        for (const name of Object.keys(DEFAULTS)) {
            if (name in entry.inputs) entry.inputs[name] = optionalInputValue(name, entry.inputs[name]);
        }
    }
    return prompt;
}
