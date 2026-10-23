// The existing views call these small adapters; editor logic stays in editor.js.
import {openEditor} from './editor.js';
import {api} from '../../scripts/api.js';
import {app} from '../../scripts/app.js';
import {openStudio, showNodes} from './studio.js';
import {cleanOptionalPrompt} from './optional_inputs.js';
import {openAutopilot, viewChanged} from './view_navigation.js';
import {mediaReferences} from './editor_media_references.js';
function editorPanel(node) {
    const values = Object.fromEntries((node.widgets || []).filter(widget => widget.name).map(widget => [widget.name, widget.value]));
    return {node: node.id, width: values.width, height: values.height, text: values.text || '', settings: Object.fromEntries(Object.entries({
        two_pass: values.two_pass, base_steps: values.base_steps, refine_steps: values.refine_steps,
        seed: values.seed, sampling_effort: values.sampling_effort}).filter(([, value]) => value !== undefined)),
        references: mediaReferences(node),
        async snapshot() {
            if (node.freevideoEditorLooping?.()) throw new Error('loop_active');
            const value = cleanOptionalPrompt(structuredClone(await app.graphToPrompt()));
            return {node: String(node.id), prompt: value.output, extra_data: {extra_pnginfo: {workflow: value.workflow || {}}}};
        }};
}
export function openEditorView(node, {studio, work = null, extend = false} = {}) {
    studio?.querySelectorAll('video,audio').forEach(media => media.pause());
    const panel = editorPanel(node);
    const progressElement = studio?.querySelector('.fv-generation-progress');
    if (progressElement) {
        panel.progressElement = progressElement;
        panel.progressSnapshot = message => {
            if (node.freevideoProgress?.chain?.id !== message.chain?.id || node.freevideoProgress?.chain?.block !== message.chain?.block || progressElement.hidden) return null;
            const number = progressElement.querySelector('.fv-generation-count')?.textContent?.match(/(\d+)%/);
            return number ? {percent: Number(number[1])} : {percent: 0};
        };
    }
    const handle = openEditor({api, app, panel, from: work ? {work, ...(extend ? {extend: true} : {})} : null, onView(view) {
        if (view === 'nodes') showNodes(node, studio);
        else if (view === 'autopilot') openAutopilot(node, {studio});
        else if (studio?.open) viewChanged('studio', node);
        else openStudio(node);
    }});
    viewChanged('editor', node);
    return handle;
}
