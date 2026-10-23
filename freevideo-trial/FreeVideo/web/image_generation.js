// Image generation's wire adapter, cancellable session and options UI. The editor
// owns its document/history; this module inserts a result through its commands.
import * as commands from './image_commands.js';
import {orientMatrix, rasterKinds, scaleSelection} from './image_editor_engine.js';

export const IMAGE_GEN_PROTOCOL = Object.freeze({
    root: '/freevideo/image-gen', header: 'X-FreeVideo-Image', upload: '/upload/image',
    installed: 'ready', phase: 'phase', bytes: 'bytes',
    token: 'token', job: 'job', prompt: 'prompt', width: 'width', height: 'height', images: 'images', seed: 'seed',
    stage: 'stage', fraction: 'fraction', file: 'file', error: 'error', name: 'name', subfolder: 'subfolder',
    states: {starting: 'queued', progress: 'running', complete: 'done', failed: 'error',
        cancelling: 'running', cancelled: 'error'},
});
export const IMAGE_GEN_POLL_MS = 500;
export const IMAGE_GEN_INFO_POLL_MS = 10000;
export const BLANK_CANVAS_RATIOS = Object.freeze(['16:9', '9:16', '1:1', '4:3', '3:4']);
export function imageGenerationSupported(platform = globalThis.navigator?.userAgentData?.platform || globalThis.navigator?.platform || '') {
    return !/Mac|iPhone|iPad/i.test(platform);
}
export function blankCanvasRatio(target) {
    return BLANK_CANVAS_RATIOS.find(ratio => {
        const [w, h] = ratio.split(':').map(Number);
        return target?.width > 0 && target?.height > 0 && target.width * h === target.height * w;
    }) || BLANK_CANVAS_RATIOS[0];
}
export function blankCanvasSize(ratio, sizes = null) {
    if (!BLANK_CANVAS_RATIOS.includes(ratio)) ratio = BLANK_CANVAS_RATIOS[0];
    if (sizes?.[ratio]) {
        const [width, height] = sizes[ratio];
        return {width, height};
    }
    const [w, h] = ratio.split(':').map(Number);
    const units = Math.floor(Math.sqrt(1024 ** 2 / (w * h * 32 ** 2)));
    return {width: w * units * 32, height: h * units * 32};
}
const failure = code => Object.assign(new Error(code || 'generation_failed'), {code: code || 'generation_failed'});

export function createImageGenClient(fetchImpl = globalThis.fetch.bind(globalThis)) {
    let token = '';
    const p = IMAGE_GEN_PROTOCOL;
    async function request(path, options) {
        const response = await fetchImpl(path, options);
        const value = await response.json();
        if (!response.ok || value[p.error] && !value[p.phase] && !value.state) throw failure(value[p.error]);
        return value;
    }
    async function post(action, value, retried = false) {
        if (!token) await info();
        try {
            return await request(`${p.root}/${action}`, {method: 'POST', headers: {
                'Content-Type': 'application/json', [p.header]: token}, body: JSON.stringify(value)});
        } catch (error) {
            // The server restarted behind an open editor: take its new token once.
            if (error.code !== 'reload' || retried) throw error;
            token = '';
            return post(action, value, true);
        }
    }
    async function info() {
        const value = await request(p.root, {cache: 'no-store'});
        token = value[p.token];
        return {...value, installed: value.installed ?? value[p.installed] ?? false};
    }
    return {
        info,
        async generate({prompt, width, height, images = [], seed}) {
            const value = await post('generate', {[p.prompt]: prompt, [p.width]: width, [p.height]: height,
                [p.images]: images, ...(seed === undefined ? {} : {[p.seed]: seed})});
            return {...value, job: value[p.job]};
        },
        async status(job) {
            const value = await post('status', {[p.job]: job});
            const phase = value[p.phase];
            return {...value, state: value.state || p.states[phase] || 'error',
                stage: value[p.stage] || (phase === 'starting' ? 'load' : ''),
                fraction: value[p.fraction], file: value[p.file], error: value[p.error],
                ...(phase === 'cancelled' ? {error: 'cancelled'} : {})};
        },
        cancel: job => post('cancel', {[p.job]: job}),
        async upload(file) {
            // ComfyUI's existing image upload stores this at input/<unique name>.
            // FreeVideo's media upload uses subdirectories the image worker rejects.
            const body = new FormData(); body.append('image', file);
            body.append('type', 'input'); body.append('overwrite', 'false');
            const value = await request(p.upload, {method: 'POST', body});
            if (!value[p.name] || value[p.subfolder] || /[/\\:]/.test(value[p.name])) throw failure('invalid_media');
            return value[p.name];
        },
    };
}

export function imagePackMessage(info, t) {
    const name = t(info?.pack_name_en || 'Image generation models', info?.pack_name_zh || '图像生成模型');
    // Match the launcher's binary size display; its optional pack_size can supply
    // the exact platform-specific label (macOS uses decimal sizes).
    const bytes = info?.[IMAGE_GEN_PROTOCOL.bytes];
    // A non-breaking space keeps the number and its unit on one line.
    const size = (info?.pack_size || (bytes > 0 ? (bytes / 2 ** 30).toFixed(1) + ' GiB' : '17.3 GB'))
        .replace(/ (?=[KMGT]i?B$)/, '\u00a0');
    return t(`Download "${name}" in the launcher first, ${size}.`, `先在启动器里下载“${name}”，${size}。`);
}
export function imageGenError(code, info, t) {
    if (code === 'pack_missing') return imagePackMessage(info, t);
    if (code === 'busy_video') return t('A video is generating. Try again when it finishes.', '视频正在生成，完成后再试。');
    if (code === 'no_memory') return t('Not enough GPU memory. Make the picture smaller in "Image size…" and try again.',
        '显存不足。在“图像大小…”里缩小后再试。');
    return t('The image could not be generated. Try again.', '没有生成成功，请再试一次。');
}

// The service accepts 256..2048 on each side; a larger canvas is generated at its
// fitted size and the result is laid over the canvas like any other layer.
export function fitGenerationSize(width, height) {
    const scale = Math.min(1, 2048 / Math.max(width, height));
    const side = value => Math.min(2048, Math.max(256, Math.round(value * scale)));
    return {width: side(width), height: side(height)};
}

export function generationContext(doc, selection, mode) {
    const layer = mode === 'edit' ? doc.layers.find(l => l.id === doc.active && rasterKinds.has(l.kind)) : null;
    return {doc, selection, layer, mode, ...fitGenerationSize(doc.crop.w, doc.crop.h)};
}
export async function uploadGenerationReference(renderer, client, context, alive = () => true) {
    let blob;
    if (context.layer) {
        await renderer.preload(context.doc);
        if (!alive()) throw failure('cancelled');
        const raster = renderer.layerImage(context.doc, context.layer, 1, true);
        blob = await new Promise((resolve, reject) => raster.toBlob(b => b ? resolve(b) : reject(failure()), 'image/png'));
    } else blob = (await renderer.export(context.doc, 'image/png')).blob;
    if (!alive()) throw failure('cancelled');
    const file = new File([blob], `freevideo-image-reference-${crypto.randomUUID()}.png`, {type: 'image/png'});
    return client.upload(file);
}

// "Edit this" can take more pictures beside the layer being edited: that layer is always image 1 and
// the others follow in the order they were added. The page offers fewer than the service accepts.
export const PAGE_REFERENCE_LIMIT = 3;
export function referenceLimit(info) {
    const most = Number(info?.max_images);
    return Number.isInteger(most) && most > 1 ? Math.min(PAGE_REFERENCE_LIMIT, most) : 1;
}
export function addReference(list, item, limit) {
    if (!item?.file || list.length >= limit - 1 || list.some(r => r.file === item.file)) return list;
    return [...list, {file: item.file, label: item.label || ''}];
}
export const removeReference = (list, file) => list.filter(r => r.file !== file);
// Media lives in folders the image worker does not read, so each extra picture is copied beside the
// first reference once and its copy is used again for later requests.
export async function uploadExtraReferences(client, references, render, copies, alive = () => true) {
    const names = [];
    for (const item of references) {
        if (!copies.has(item.file)) {
            const blob = await render(item.file);
            if (!alive()) throw failure('cancelled');
            const name = await client.upload(new File([blob], `freevideo-image-reference-${crypto.randomUUID()}.png`, {type: 'image/png'}));
            if (!alive()) throw failure('cancelled');
            copies.set(item.file, name);
        }
        names.push(copies.get(item.file));
    }
    return names;
}

export function insertGenerationResult(doc, result, context, t) {
    const sx = doc.width / context.doc.width, sy = doc.height / context.doc.height;
    const reference = context.mode === 'edit' && context.layer;
    const above = doc.layers.find(l => l.id === reference?.id) || doc.layers.at(-1);
    let next = commands.addImageLayer({...doc, active: above?.id || null}, {
        ...result, name: context.mode === 'new' ? t('Generated', '生成') : t('Edited', '改图')});
    let geometry;
    if (reference) {
        geometry = {cx: reference.cx * sx, cy: reference.cy * sy, w: reference.w * sx, h: reference.h * sy,
            rotation: reference.rotation, flipX: reference.flipX, flipY: reference.flipY};
    } else {
        const c = doc.crop, point = orientMatrix(doc).inverse().transformPoint(new DOMPoint(c.x + c.w / 2, c.y + c.h / 2));
        geometry = {cx: point.x, cy: point.y, w: c.w, h: c.h, rotation: -doc.rotate, flipX: doc.flipX, flipY: doc.flipY};
    }
    next = {...next, layers: next.layers.map(l => l.id === next.active ? {...l, ...geometry} : l)};
    if (context.selection) next = commands.maskFromSelection(next, next.active, scaleSelection(context.selection, sx, sy));
    return next;
}

// The worker counts every stage from 0 to 1. One bar for the whole picture: each stage owns a
// slice in the order it runs (the reference encode only exists with reference images), and the
// bar stays below 100% until the result is placed.
const STAGE_SLICES = {
    new: [['load', .15], ['text', .15], ['denoise', .5], ['decode', .2]],
    edit: [['load', .15], ['text', .15], ['encode', .05], ['denoise', .45], ['decode', .2]],
};
export function imageGenProgress(stage, fraction, withImages = false) {
    const own = Math.min(1, Math.max(0, Number.isFinite(fraction) ? fraction : 0));
    let start = 0;
    for (const [name, weight] of STAGE_SLICES[withImages ? 'edit' : 'new']) {
        if (name === stage) return Math.min(.99, start + weight * own);
        start += weight;
    }
    return Math.min(.99, own);
}

// An epoch rejects late uploads/status/results. A generate response arriving
// after Stop still has to be cancelled, even though its job was not known yet.
export function createImageGenSession({client, prepare, apply, onChange = () => {},
    schedule = setTimeout, unschedule = clearTimeout,
    visible = () => globalThis.document?.visibilityState !== 'hidden'}) {
    let epoch = 0, timer = null, infoTimer = null, disposed = false, checking = null;
    let state = {info: null, checking: false, running: false, job: null, fraction: 0, stage: '', error: ''};
    const emit = patch => { state = {...state, ...patch}; if (!disposed) onChange(state); };
    const cancelJob = job => Promise.resolve().then(() => client.cancel(job)).catch(() => {});
    function scheduleInfo() {
        unschedule(infoTimer); infoTimer = null;
        if (disposed || state.info?.installed) return;
        infoTimer = schedule(() => {
            infoTimer = null;
            if (visible()) void check(); else scheduleInfo();
        }, IMAGE_GEN_INFO_POLL_MS);
    }
    async function check() {
        if (checking || disposed) return checking;
        emit({checking: true});
        checking = (async () => {
            try { const info = await client.info(); if (!disposed) emit({info}); }
            catch (error) { if (!disposed && !state.running) emit({error: error.code || error.message}); }
            finally { checking = null; if (!disposed) { emit({checking: false}); scheduleInfo(); } }
        })();
        return checking;
    }
    async function start(request) {
        if (state.running || disposed || !request.prompt.trim() || !state.info?.installed) return;
        const current = ++epoch;
        emit({running: true, job: null, fraction: 0, stage: '', error: ''});
        const alive = () => current === epoch && !disposed;
        let withImages = false;
        async function poll(job, context) {
            try {
                const row = await client.status(job);
                if (!alive()) return;
                const fraction = imageGenProgress(row.stage, row.fraction, withImages);
                emit({fraction: Math.max(state.fraction, fraction), stage: row.stage || ''});
                if (row.state === 'done') {
                    if (!row.file) throw failure();
                    await apply(row, context, alive);
                    if (alive()) emit({running: false, job: null, fraction: 1, stage: ''});
                } else if (row.state === 'error') throw failure(row.error);
                else timer = schedule(() => { timer = null; void poll(job, context); }, IMAGE_GEN_POLL_MS);
            } catch (error) {
                if (alive()) {
                    void cancelJob(job);
                    emit({running: false, job: null, stage: '', error: error.code || error.message});
                }
            }
        }
        try {
            const {context, images = []} = await prepare(request, alive);
            if (!alive()) return;
            withImages = images.length > 0;
            const {job} = await client.generate({prompt: request.prompt, width: context.width, height: context.height, images});
            if (!job) throw failure();
            if (!alive()) { await cancelJob(job); return; }
            emit({job});
            timer = schedule(() => { timer = null; void poll(job, context); }, IMAGE_GEN_POLL_MS);
        } catch (error) {
            if (alive()) emit({running: false, job: null, stage: '', error: error.code || error.message});
        }
    }
    function cancel() {
        ++epoch; unschedule(timer); timer = null;
        const job = state.job;
        emit({running: false, job: null, stage: '', fraction: 0, error: ''});
        return job ? cancelJob(job) : Promise.resolve();
    }
    return {check, start, cancel, clearError: () => emit({error: ''}), state: () => state,
        dispose() { disposed = true; unschedule(infoTimer); infoTimer = null; return cancel(); }};
}

export function createImageGeneration({client, renderer, t, getDoc, getSelection, commit, el, button, segmented,
    library = [], resolve = file => file, icon = () => '', onRatioChange}) {
    let mode = 'edit', prompt = '', mounted = null, references = [];
    const copies = new Map();
    // A reference is sent no larger than the largest picture the service makes.
    async function referencePNG(file) {
        const image = await renderer.image(file);
        const k = Math.min(1, 2048 / Math.max(image.naturalWidth, image.naturalHeight));
        const canvas = el('canvas'); canvas.width = Math.max(1, Math.round(image.naturalWidth * k)); canvas.height = Math.max(1, Math.round(image.naturalHeight * k));
        canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
        return new Promise((done, fail) => canvas.toBlob(b => b ? done(b) : fail(failure()), 'image/png'));
    }
    const session = createImageGenSession({client,
        prepare: async (request, alive) => {
            const context = generationContext(getDoc(), getSelection(), request.mode);
            const images = request.mode === 'edit' ? [await uploadGenerationReference(renderer, client, context, alive),
                ...await uploadExtraReferences(client, request.references || [], referencePNG, copies, alive)] : [];
            return {context, images};
        },
        apply: async (result, context, alive) => {
            const image = await renderer.image(result.file);
            if (!alive()) return;
            renderer.images.get(result.file).value = image;
            commit(insertGenerationResult(getDoc(), {src: result.file, nw: image.naturalWidth, nh: image.naturalHeight}, context, t));
        }, onChange: update,
    });
    const limit = () => referenceLimit(session.state().info);
    const chosen = () => mode === 'edit' ? references.slice(0, limit() - 1) : [];
    const start = () => session.start({mode, prompt, references: chosen()});
    function drawEdited(canvas) {
        try {
            const doc = getDoc(), layer = generationContext(doc, null, 'edit').layer;
            const scale = Math.min(1, 128 / (layer ? Math.max(layer.nw, layer.nh) : Math.max(doc.width, doc.height)));
            const image = layer ? renderer.layerImage(doc, layer, scale) : renderer.composite(doc, scale);
            const k = Math.max(canvas.width / image.width, canvas.height / image.height);
            canvas.getContext('2d').drawImage(image, (canvas.width - image.width * k) / 2, (canvas.height - image.height * k) / 2, image.width * k, image.height * k);
        } catch { /* drawn on the next update once its image has loaded */ }
    }
    function renderReferences(refs, disabled) {
        const most = limit(), list = chosen();
        refs.hidden = mode !== 'edit' || most < 2 || !(library.length || list.length);
        refs.replaceChildren();
        if (refs.hidden) return;
        const slot = (number, picture, name) => {
            const item = el('span', null, 'fv-ie-gen-ref'); item.setAttribute('role', 'listitem');
            item.setAttribute('aria-label', name);
            item.append(picture, el('b', String(number)));
            return item;
        };
        const edited = el('canvas'); edited.width = edited.height = 56; drawEdited(edited);
        refs.append(slot(1, edited, t('Image 1', '图 1')));
        list.forEach((reference, index) => {
            const picture = el('img'); picture.src = resolve(reference.file); picture.alt = '';
            const item = slot(index + 2, picture, `${t('Image', '图')} ${index + 2}`);
            const remove = button('×', t('Remove', '移除'), () => { references = removeReference(references, reference.file); update(); }, 'fv-ie-gen-ref-remove');
            remove.setAttribute('aria-label', t('Remove', '移除')); remove.disabled = disabled;
            item.append(remove); refs.append(item);
        });
        const rest = library.filter(item => !list.some(r => r.file === item.file));
        const menu = el('details', null, 'fv-ie-menu fv-ie-gen-ref-add');
        const summary = el('summary'); summary.innerHTML = icon('plus', 16);
        summary.title = t('Reference image', '参考图'); summary.setAttribute('aria-label', summary.title);
        const full = disabled || list.length >= most - 1 || !rest.length;
        summary.setAttribute('aria-disabled', String(full)); if (full) summary.tabIndex = -1;
        summary.onclick = event => { if (full) event.preventDefault(); };
        const choices = el('div', null, 'fv-ie-menu-list');
        for (const item of rest) {
            const choice = button('', null, () => { references = addReference(references, item, most); update(); }, 'fv-ie-menu-item');
            const picture = el('img'); picture.src = resolve(item.file); picture.alt = ''; picture.loading = 'lazy';
            choice.append(picture, el('span', item.label)); choices.append(choice);
        }
        menu.append(summary, choices); refs.append(menu);
    }
    function update() {
        if (!mounted?.bar.isConnected) return;
        const {input, action, note, meter, fill, group, bar, refs, ratio} = mounted, state = session.state();
        const missing = !state.running && state.info && !state.info.installed;
        const disabled = state.running || state.checking || !state.info?.installed;
        const empty = !getDoc().layers.length;
        if (empty) mode = 'new';
        bar.dataset.empty = String(empty);
        if (ratio) {
            ratio.hidden = !empty; ratio.disabled = state.running;
            ratio.value = BLANK_CANVAS_RATIOS.includes(getDoc().ratio) ? getDoc().ratio : blankCanvasRatio(getDoc());
        }
        group.querySelectorAll('button').forEach(b => {
            b.disabled = disabled || (empty && b.dataset.value === 'edit');
            b.setAttribute('aria-pressed', String(b.dataset.value === mode));
        }); input.disabled = disabled;
        renderReferences(refs, disabled);
        input.placeholder = mode === 'edit' ? t('What to change', '要改什么') : t('Describe the picture', '描述画面');
        input.setAttribute('aria-label', input.placeholder);
        action.textContent = state.running ? t('Stop', '停止') : t('Generate', '生成');
        action.classList.toggle('fv-ie-primary', !state.running);
        action.disabled = !state.running && (disabled || !prompt.trim()); action.hidden = !!missing;
        const percent = Math.floor(state.fraction * 100) + '%';
        note.textContent = missing ? imagePackMessage(state.info, t) : state.error ? imageGenError(state.error, state.info, t)
            : state.running ? (state.stage === 'load' ? t('Loading the model', '加载模型') + ' ' : '') + percent : '';
        note.hidden = !note.textContent;
        bar.dataset.running = String(state.running); bar.dataset.message = String(!!missing || !!state.error);
        meter.hidden = !state.running; meter.setAttribute('aria-valuenow', String(Math.floor(state.fraction * 100)));
        fill.style.width = state.fraction * 100 + '%';
    }
    function mount(bar) {
        bar.classList.add('fv-ie-generation');
        const group = segmented([['edit', t('Edit this', '改这张')], ['new', t('New image', '生成一张')]], mode,
            value => { mode = value; update(); }, t('Generate with AI', 'AI 生成')).group;
        let ratio = null;
        if (!getDoc().layers.length) {
            ratio = el('select', null, 'fv-ie-select'); ratio.id = 'fv-ie-gen-ratio';
            ratio.setAttribute('aria-label', t('Shape', '比例'));
            for (const value of BLANK_CANVAS_RATIOS) {
                const option = el('option', value); option.value = value; ratio.append(option);
            }
            ratio.onchange = () => {
                if (!getDoc().layers.length && !session.state().running) onRatioChange?.(ratio.value);
                update();
            };
        }
        const field = el('div', null, 'fv-ie-gen-field');
        const refs = el('div', null, 'fv-ie-gen-refs'); refs.setAttribute('role', 'list');
        refs.setAttribute('aria-label', t('Reference images', '参考图'));
        const box = el('div', null, 'fv-ie-gen-box');
        const input = el('textarea', null, 'fv-ie-gen-prompt'); input.rows = 1; input.maxLength = 2000; input.value = prompt;
        box.append(input); field.append(refs, box);
        const note = el('span', '', 'fv-ie-opt-note fv-ie-gen-note'); note.setAttribute('role', 'status');
        const action = button(t('Generate', '生成'), null, () => {
            if (session.state().running) void session.cancel(); else void start();
        }, 'fv-ie-button fv-ie-primary');
        const meter = el('div', null, 'fv-ie-gen-meter'), fill = el('i'); meter.append(fill);
        meter.setAttribute('role', 'progressbar'); meter.setAttribute('aria-label', t('Generate with AI', 'AI 生成'));
        meter.setAttribute('aria-valuemin', '0'); meter.setAttribute('aria-valuemax', '100');
        bar.append(group);
        if (ratio) bar.append(ratio);
        bar.append(field, note, action, meter);
        mounted = {bar, input, action, note, meter, fill, group, refs, ratio};
        const grow = () => { input.style.height = '0px'; input.style.height = Math.min(80, Math.max(32, input.scrollHeight + 2)) + 'px'; };
        input.oninput = () => { prompt = input.value; session.clearError(); grow(); };
        input.onkeydown = event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !event.ctrlKey && !event.metaKey) {
                event.preventDefault(); void start();
            }
        };
        grow(); update();
    }
    return {mount, unmount() { mounted = null; }, selected: () => session.check(), cancel: session.cancel,
        dispose: session.dispose, state: session.state};
}
