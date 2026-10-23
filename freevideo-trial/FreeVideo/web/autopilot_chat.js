// The conversation with the connected agent: what the user says, what the agent answers, and the agent's jobs as
// cards at the place they happened. Reads and sends use the page session; the agent's token never enters the page.
import {agentGet, agentPost} from './agent_session.js';
import { estimatedFraction, remainingAbove, remainingShown } from './generation_progress.js';
import {emptyConversations, hasConversations, mergeConversations, runningElsewhere, selectConversation} from './autopilot_conversations.js';

const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = new URL('./autopilot_chat.css', import.meta.url).href; document.head.append(css);

function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function glyph(path, width = 2.2) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('stroke-width', String(width));
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', path); svg.append(p);
    return svg;
}
const press = (cls, text, action) => { const b = el('button', cls, text); b.type = 'button'; b.onclick = action; return b; };
let chatNumber = 0;

const WORKING = ['running', 'queued', 'waiting'], VIDEOS = ['generate', 'assemble'];
// What a job with no picture of its own is doing, in the reader's language.
const QUIET = {vlm: ['Checking', '检查中'], enhance: ['Polishing', '润色中']};

export const about = (seconds, t) => seconds >= 60 ? t(`About ${Math.ceil(seconds / 60)} min`, `约 ${Math.ceil(seconds / 60)} 分钟`) : t('Under 1 min', '不到 1 分钟');
export function clock(seconds) { const s = Math.max(0, Math.round(seconds)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }
export const jobName = (job, t) => job.label || (job.kind === 'image' ? t('Picture', '图片') : t('Video', '视频'));
export const jobFraction = job => Math.max(0, Math.min(1, Number(job.progress?.fraction) || 0));
// What a job's last progress stands for `age` seconds after it was made, by the creation panel's rule.
export function jobEstimate(job, age) {
    const e = job.progress?.estimate, sent = e?.overall ? estimatedFraction(e, e.overall, age, age) : null;
    return Math.max(jobFraction(job), sent ?? 0);
}
// The level a job shows, given the engine's number (`base`), the time it says is left and the clock. The engine's
// number can stand for a long while: a model loading for the first time runs far past the time the engine gave it,
// and a video in several parts has no timing at all. While it stands the level still rises, at the pace of the time
// left, slowing down, and by no more than a quarter of what remains. When the number moves again, what was added is
// kept only as far as the number has not caught up with it: the rest of the way is then drawn shorter, so the level
// neither waits nor goes back and is full at the end, and a run that goes as the engine said shows the engine's number.
const DRIFT = .25, RISE = .0005;
export const newLevel = () => ({value: 0, top: null, since: 0, scale: 1});
// The time left a running job shows, by the creation panel's rule: once measured never raised, and gone once its last
// minute has passed. `row` is what the job showed before (none yet: it starts at the engine's number); `seconds` is null
// from the moment the time has run out.
export function jobLeft(row, sent, source, time) {
    if (!row) {
        if (!(sent > 0)) return null;
        row = {seconds: sent, at: time, minute: null, last: 0, source: null, above: 0};
    }
    if (row.seconds === null) return row;
    // Before the run is measured the engine's number is an estimate from earlier runs: follow it up as well as down.
    const named = typeof source === 'string', initial = source === 'similar';
    // The first number that is not that estimate replaces it once, up or down, and its last minute starts over.
    if (named && !initial && row.source === 'similar' && sent > 0) { row.seconds = sent; row.minute = null; }
    if (named) row.source = source;
    const target = sent > 0 ? sent : null; row.above = remainingAbove(row.above, row.seconds, target, time - row.at);
    row.seconds = remainingShown(row.seconds, target, time - row.at, initial, row.above); row.at = time;
    if (row.seconds < 60 && row.minute === null) { row.minute = time; row.last = row.seconds; }
    // An estimate that rises out of its last minute starts that minute over.
    else if (row.seconds >= 60 && initial) row.minute = null;
    if (row.seconds <= 0 || row.minute !== null && time - row.minute >= row.last) row.seconds = null;
    return row;
}
export function jobLevel(row, base, left, time) {
    if (row.top === null || base > row.top + RISE) {
        if (row.top !== null && base < 1) row.scale = Math.min(row.scale, (1 - row.value) / (1 - base));
        row.top = base; row.since = time;
    }
    // The number itself, or where standing since it last moved has brought the level: whichever is further on.
    const from = 1 - row.scale * (1 - row.top), level = 1 - row.scale * (1 - Math.max(base, row.top));
    const more = left > 0 ? (1 - from) * DRIFT * (1 - Math.exp(-Math.max(0, time - row.since) / (DRIFT * left))) : 0;
    return row.value = Math.max(row.value, Math.min(.99, Math.max(level, from + more)));
}
// working, done, stopped or failed: which card a job shows.
export const jobMode = job => WORKING.includes(job.status) ? 'working' : job.status === 'succeeded' ? 'done' : job.status === 'cancelled' ? 'stopped' : 'failed';
const SAVING = ['decode', 'finishing', 'assembling'], stepped = p => p.phase === 'sampling' && p.step?.total && p.step.done >= 1;
// The one line that says where a job is. No step count is written unless the engine gave one.
export function jobLine(job, t) {
    const p = job.progress || {};
    if (job.status !== 'running') return t('Queued', '排队中');
    if (stepped(p)) return t(`Step ${p.step.done} / ${p.step.total}`, `生成 ${p.step.done} / ${p.step.total}`);
    if (SAVING.includes(p.phase)) return t('Saving', '保存中');
    if (p.phase === 'encoding') return t('Reading the prompt', '读取提示词');
    // Before the first step of the first part the model is still settling in: the line does not turn back to "Preparing".
    if (['load', 'loading'].includes(p.phase) || p.phase === 'sampling' && !(p.block?.done > 0)) return t('Loading the model', '加载模型');
    return t('Preparing', '准备中');
}
// The line a card shows. After the last step, and again after saving, the engine has a moment with no step and no
// stage to report: a card that has counted steps or said "Saving" for a part keeps that line until there is a newer
// one, and does not go back to the lines from before the first step. `said` is the card's own memory.
export function cardLine(said, job, t) {
    const p = job.progress || {}, part = p.block?.index ?? 0;
    if (job.status !== 'running' || said.part !== part) said.last = null;
    said.part = part;
    if (job.status === 'running' && (stepped(p) || SAVING.includes(p.phase))) said.last = job;
    return jobLine(said.last || job, t);
}
export function jobMeta(job, t) {
    const parts = [];
    if (job.width > 0 && job.height > 0) parts.push(`${job.width} × ${job.height}`);
    if (job.seconds > 0) parts.push(t(`${job.seconds} s`, `${job.seconds} 秒`));
    return parts.join(' · ');
}
// One number per part of a long video: 1 when made, how far along for the one being made, 0 for the rest.
export function jobParts(job) {
    const block = job.progress?.block, step = job.progress?.step;
    if (!(block?.total > 1)) return [];
    const inside = job.progress.phase === 'sampling' && step?.total ? Math.min(1, step.done / step.total) : 0;
    return Array.from({length: block.total}, (_, i) => i < (block.done || 0) ? 1 : i === block.index - 1 ? inside : 0);
}

export const emptyChat = () => ({session: undefined, items: new Map(), jobs: {}, confirms: {}, last: 0, read: 0, agent: {}, current: null, active: 0});
// One answer from the server folded into what the page already has: entries add up by their number, jobs are
// replaced by id (a card keeps its last state after the server stops listing its job), and so are the answers to its questions.
export function chatMerge(state, data) {
    const items = new Map(state.items);
    for (const item of data.items || []) if (['message', 'job', 'confirm'].includes(item.type) && Number.isFinite(item.seq)) items.set(item.seq, item);
    const read = Math.max(state.read, Number(data.read_seq) || 0, ...(data.items || []).filter(item => item.read === true).map(item => item.seq));
    return {session: data.session ?? null, items, jobs: {...state.jobs, ...(data.jobs || {})}, confirms: {...state.confirms, ...(data.confirms || {})}, read,
        last: Math.max(state.last, Number(data.last_seq) || 0, ...items.keys()), agent: data.agent || {},
        current: data.current || null, active: Number(data.active) || 0};
}
// The entries in order. A user's sentence counts as taken once the agent has read it or has said or done anything after it.
export function chatEntries(state) {
    const list = [...state.items.values()].sort((a, b) => a.seq - b.seq);
    let answered = 0;
    for (const item of list) if (item.type !== 'message' || item.role !== 'user') answered = item.seq;
    return list.map(item => item.type === 'message' && item.role === 'user'
        ? {...item, taken: item.read === true || item.seq <= state.read || item.seq < answered} : item);
}
// Whether a sentence sent now reaches anyone: the agent is waiting for one, or is at work and will come back for it.
export const canSend = state => state.agent?.connected === true && (state.agent.listening !== false || state.active > 0);

function newId() {
    const bytes = crypto.getRandomValues(new Uint8Array(12));
    return 'm-' + [...bytes].map(b => b.toString(36).padStart(2, '0')).join('').slice(0, 20);
}

// open(job) shows a finished video in Creations, edit(job) takes it to the editing view. shown() says whether the
// user can see the conversation; the page calls sync() whenever that may have changed. changed(view) follows every
// answer: {known, agent, current, active, any}.
export function agentChat(t, api, {open, edit, shown = () => true, changed = () => {}, interval = 1500} = {}) {
    const element = el('section', 'fv-chat'), main = el('div', 'fv-chat-main'), scroller = el('div', 'fv-chat-scroll'), log = el('ol', 'fv-chat-log');
    log.setAttribute('role', 'log'); log.setAttribute('aria-label', t('Conversation', '对话'));
    const down = press('fv-chat-down', null, () => { scroller.scrollTo({top: scroller.scrollHeight, behavior: 'smooth'}); });
    down.append(glyph('M12 5v14M5 12l7 7 7-7')); down.setAttribute('aria-label', t('Latest', '最新')); down.hidden = true;
    const form = el('form', 'fv-chat-input'), input = el('textarea'), sendButton = el('button', 'fv-chat-send');
    input.rows = 1; input.maxLength = 8000; input.setAttribute('aria-label', t('Message the agent', '对 Agent 说'));
    sendButton.type = 'submit'; sendButton.setAttribute('aria-label', t('Send', '发送')); sendButton.append(glyph('M12 19V5M5 12l7-7 7 7'));
    form.append(input, sendButton); scroller.append(log); main.append(scroller, down, form); element.append(main);

    let state = emptyChat(), pending = [], known = false, stopped = false, timer = null, busy = false, failures = 0;
    let conversations = emptyConversations(), selectedSession, selection = 0, reread = false, focusSession = null, creating = false;
    // Work under way in another conversation while this one has none: {session, job, ids}. The page's header keeps it in sight.
    let away = null;
    let listBusy = false, listAgain = false, listAt = -Infinity;
    const listInterval = 10000;
    const sidebar = el('nav', 'fv-chat-conversations'), list = el('div', 'fv-chat-conversation-list'), tools = el('div', 'fv-chat-tools');
    sidebar.id = `fv-chat-conversations-${++chatNumber}`; sidebar.setAttribute('aria-label', t('Chats', '对话')); sidebar.hidden = true;
    const newChat = press('fv-chat-new', t('New chat', '新对话'), () => void startChat());
    newChat.prepend(glyph('M12 5v14M5 12h14')); newChat.title = t('New chat', '新对话');
    const chats = press('fv-chat-chats', null, () => drawer(chats.getAttribute('aria-expanded') !== 'true'));
    const chatsDot = el('i', 'fv-chat-running'); chatsDot.setAttribute('aria-hidden', 'true'); chatsDot.hidden = true;
    chats.append(glyph('M4 5h16v12H9l-5 4V5M8 9h8M8 13h5'), chatsDot);
    chats.title = t('Chats', '对话'); chats.setAttribute('aria-label', chats.title);
    chats.setAttribute('aria-controls', sidebar.id); chats.setAttribute('aria-expanded', 'false');
    tools.hidden = true; tools.append(chats); main.prepend(tools); sidebar.append(newChat, list); element.prepend(sidebar);
    const listNodes = new Map(), narrow = () => window.matchMedia('(max-width: 720px)').matches;
    function drawer(on, restore = false) {
        element.dataset.chatsOpen = String(on); chats.setAttribute('aria-expanded', String(on));
        // Only the overlay needs to keep keyboard focus in its list.
        main.inert = on && narrow();
        if (on) (list.querySelector('[aria-current]') || newChat).focus();
        else if (restore) chats.focus();
    }
    function renderConversations() {
        const visible = hasConversations(conversations);
        element.dataset.conversations = String(visible); sidebar.hidden = tools.hidden = !visible;
        if (!visible) drawer(false);
        newChat.disabled = creating; chatsDot.hidden = !conversations.conversations.some(row => row.running > 0);
        const keep = new Set(conversations.conversations.map(row => row.id));
        for (const [id, node] of listNodes) if (!keep.has(id)) { node.button.remove(); listNodes.delete(id); }
        conversations.conversations.forEach((row, index) => {
            let node = listNodes.get(row.id);
            if (!node) {
                const button = press('fv-chat-conversation', null, () => chooseChat(row.id)), dot = el('i', 'fv-chat-running'), title = el('span');
                button.dataset.session = row.id; dot.setAttribute('aria-hidden', 'true'); button.append(dot, title);
                listNodes.set(row.id, node = {button, dot, title});
            }
            node.title.textContent = row.title; node.button.title = row.title; node.dot.hidden = row.running <= 0;
            if (row.id === conversations.current) node.button.setAttribute('aria-current', 'true'); else node.button.removeAttribute('aria-current');
            if (list.children[index] !== node.button) list.insertBefore(node.button, list.children[index] || null);
        });
    }
    function chooseChat(session, focus = false) {
        selectedSession = session; selection++; pinned = true; away = null;
        conversations = selectConversation(conversations, session); renderConversations();
        input.value = ''; grow(); drawer(false);
        focusSession = focus ? session : null;
        if (focus && session === state.session) input.focus(); else if (narrow()) chats.focus();
        render(); void readConversations(true); void poll();
    }
    async function startChat() {
        if (creating || !active() || conversations.supported !== true) return;
        creating = true; renderConversations(); render();
        try {
            const response = await agentPost(api, '/freevideo/agent/chat/new', {});
            if (stopped) return;
            if (response.ok) {
                const data = await response.json();
                if (typeof data.session === 'string' && data.session) chooseChat(data.session, true);
            } else if (response.status === 409) { state = {...state, agent: {connected: false, name: null}}; report(); }
        } catch { /* Keep the current conversation available for another try. */ }
        finally { creating = false; if (!stopped) { renderConversations(); render(); } }
    }
    async function readConversations(force = false) {
        if (!active() || conversations.supported === false) return;
        if (listBusy) { if (force) listAgain = true; return; }
        if (!force && performance.now() - listAt < listInterval) return;
        listBusy = true; listAt = performance.now();
        try {
            const response = await agentGet(api, '/freevideo/agent/chat/list', {signal: closed.signal});
            if (stopped) return;
            // The body is awaited first: a conversation chosen meanwhile must stay the current one.
            const data = response.ok ? await response.json() : null;
            if (stopped) return;
            conversations = mergeConversations(conversations, data, response.status);
            renderConversations();
            if (conversations.supported === false && selectedSession !== undefined) { selectedSession = undefined; selection++; void poll(); }
        } catch { /* List failures do not interrupt reading or sending. */ }
        finally { listBusy = false; }
        if (listAgain) { listAgain = false; void readConversations(true); }
    }
    const outside = event => {
        if (chats.getAttribute('aria-expanded') === 'true' && !sidebar.contains(event.target) && !chats.contains(event.target)) drawer(false, true);
    };
    const keys = event => {
        if (chats.getAttribute('aria-expanded') !== 'true') return;
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); drawer(false, true); }
        else if (event.key === 'Tab' && narrow()) {
            const buttons = [...sidebar.querySelectorAll('button')].filter(button => !button.disabled);
            if (!buttons.length) return;
            if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons.at(-1).focus(); }
            else if (!event.shiftKey && document.activeElement === buttons.at(-1)) { event.preventDefault(); buttons[0].focus(); }
        }
    };
    const resize = () => { if (!narrow()) drawer(false); };
    document.addEventListener('pointerdown', outside, true); document.addEventListener('keydown', keys, true);
    window.addEventListener('resize', resize);
    // Whether the reader is at the newest entry. It holds while the conversation is out of sight, which forgets where it was scrolled.
    let pinned = true;
    const closed = new AbortController();
    const nodes = new Map(), answers = new Map(), stopping = new Set();
    // The fraction each job shows: the estimate, never backwards, short of 100% until the video is saved.
    const levels = new Map();
    function fractionOf(job) {
        const p = job.progress || {}, {age_seconds: sent, ...sample} = p.estimate || {fraction: p.fraction};
        const key = JSON.stringify(sample), time = performance.now() / 1000;
        // A job that stopped or failed and is tried again starts from the beginning, not from where the last try got to.
        if (job.status !== 'running' && job.status !== 'succeeded') levels.delete(job.id);
        let row = levels.get(job.id);
        if (!row) levels.set(job.id, row = {key: null, at: 0, job: null, level: newLevel()});
        // remaining_seconds counts down between samples; the one that came with the sample is the one to move by.
        if (row.key !== key) { row.key = key; row.at = time - (sent > 0 ? sent : 0); row.job = job; }
        if (job.status === 'running') jobLevel(row.level, jobEstimate(row.job, time - row.at), row.job.progress?.remaining_seconds, time);
        return row.level.value;
    }
    const times = new Map();
    function leftOf(job) {
        if (job.status !== 'running') { times.delete(job.id); return null; }
        const row = jobLeft(times.get(job.id), job.progress?.remaining_seconds,
            job.progress?.estimate?.overall?.remaining_source, performance.now() / 1000);
        if (row) times.set(job.id, row);
        return row ? row.seconds : null;
    }
    const active = () => !stopped && element.isConnected && !document.hidden && shown();
    const sendingAllowed = () => !creating && (!selectedSession || selectedSession === state.session) && canSend(state);

    // ---- one entry of the conversation each ----
    function message(role) {
        const item = el('li', role === 'user' ? 'fv-chat-me' : 'fv-chat-ai'), text = el('p'); item.append(text);
        return {element: item, update(entry) { text.textContent = entry.text; if (role === 'user') item.dataset.taken = String(entry.taken !== false); }};
    }
    function preview(job) {
        const box = el('div', 'fv-chat-preview');
        const shape = (w, h) => { if (w > 0 && h > 0) { box.style.aspectRatio = `${w} / ${h}`; box.dataset.shape = w > h * 1.1 ? 'wide' : 'tall'; } };
        shape(job.width, job.height);
        return {box, shape};
    }
    function working(item, job) {
        const {box} = preview(job), water = el('i', 'fv-chat-water'), percent = el('b', 'fv-chat-percent'); box.append(water, percent);
        const info = el('div', 'fv-chat-info'), head = el('div'), name = el('h3'), meta = el('p', 'fv-chat-meta'); head.append(name, meta);
        const middle = el('div', 'fv-chat-where'), parts = el('div', 'fv-chat-parts'), line = el('p', 'fv-chat-line'), part = el('span'), step = el('span'); line.append(part, step);
        middle.append(parts, line);
        const foot = el('div', 'fv-chat-actions'), left = el('span', 'fv-chat-left');
        const stop = press('fv-chat-stop', null, async () => {
            stopping.add(job.id); render();
            try { await agentPost(api, '/freevideo/agent/activity/cancel', {id: job.id}); } catch { stopping.delete(job.id); }
            poll();
        });
        foot.append(left, stop); info.append(head, middle, foot); item.replaceChildren(box, info);
        const said = {};
        // The number rides on the water, and goes under the line once there is no room left above it.
        const level = next => {
            const fraction = fractionOf(next);
            box.style.setProperty('--level', `${fraction * 100}%`);
            percent.textContent = next.status === 'running' && fraction >= .01 ? `${Math.floor(fraction * 100)}%` : '';
            const high = box.clientHeight;
            box.dataset.under = String(high > 0 && high * (1 - fraction) < percent.offsetHeight + 10);
            const seconds = leftOf(next);
            left.textContent = seconds === null ? '' : about(seconds, t);
        };
        item.tick = () => level(state.jobs[job.id] || job);
        return next => {
            const cells = jobParts(next);
            level(next);
            name.textContent = jobName(next, t); meta.textContent = jobMeta(next, t); meta.hidden = !meta.textContent;
            while (parts.children.length > cells.length) parts.lastChild.remove();
            while (parts.children.length < cells.length) parts.append(el('i'));
            cells.forEach((value, index) => parts.children[index].style.setProperty('--w', `${value * 100}%`));
            parts.hidden = !cells.length;
            const block = next.progress?.block;
            const where = cardLine(said, next, t);
            part.textContent = cells.length ? t(`Part ${block.index} / ${block.total}`, `第 ${block.index} / ${block.total} 段`) : where;
            step.textContent = cells.length ? where : '';
            const going = stopping.has(next.id);
            stop.disabled = going; stop.textContent = going ? t('Stopping', '正在停止') : t('Stop', '停止');
            stop.setAttribute('aria-label', t('Stop ', '停止 ') + jobName(next, t));
        };
    }
    function done(item, job) {
        const info = el('div', 'fv-chat-info'), head = el('div'), name = el('h3'), meta = el('p', 'fv-chat-meta'); head.append(name, meta);
        const foot = el('div', 'fv-chat-actions');
        const show = press('fv-chat-open', t('Open', '打开'), () => open(job));
        const cut = press('fv-chat-edit', t('Edit', '剪辑'), () => edit(job));
        if (job.work) foot.append(show, cut);
        info.append(head, foot);
        const children = [info];
        if (job.thumbnail || job.play) {
            const {box, shape} = preview(job), length = el('span', 'fv-chat-length', job.seconds > 0 ? clock(job.seconds) : '');
            if (job.thumbnail) {
                const image = el('img'); image.alt = ''; image.src = api.apiURL(job.thumbnail);
                image.onload = () => { if (!box.style.aspectRatio) shape(image.naturalWidth, image.naturalHeight); };
                box.append(image);
            }
            if (job.play) {
                // The video plays inside its frame, with its sound; the line under it follows and can be dragged.
                let video = null;
                const toggle = press('fv-chat-play', null, () => {
                    if (!video) {
                        video = el('video'); video.playsInline = true; video.src = api.apiURL(job.play);
                        const seek = el('input', 'fv-chat-seek'); seek.type = 'range'; seek.min = '0'; seek.max = '1000'; seek.value = '0';
                        seek.setAttribute('aria-label', t('Position', '播放位置'));
                        video.onloadedmetadata = () => shape(video.videoWidth, video.videoHeight);
                        video.ontimeupdate = () => { if (video.duration) seek.value = String(Math.round(video.currentTime / video.duration * 1000)); };
                        video.onplay = video.onpause = video.onended = () => { box.dataset.playing = String(!video.paused && !video.ended); label(); };
                        seek.oninput = () => { if (video.duration) video.currentTime = seek.value / 1000 * video.duration; };
                        box.prepend(video); box.append(seek); box.dataset.video = 'true';
                    }
                    if (video.paused || video.ended) void video.play().catch(() => {}); else video.pause();
                });
                const label = () => toggle.setAttribute('aria-label', (box.dataset.playing === 'true' ? t('Pause ', '暂停 ') : t('Play ', '播放 ')) + jobName(job, t));
                label(); box.append(toggle);
            }
            if (length.textContent) box.append(length);
            children.unshift(box);
        }
        item.replaceChildren(...children);
        return (next, latest) => {
            name.textContent = jobName(next, t); meta.textContent = jobMeta(next, t); meta.hidden = !meta.textContent;
            show.classList.toggle('fv-primary', latest);
        };
    }
    function jobCard() {
        const item = el('li', 'fv-chat-job');
        let mode = null, apply = null;
        return {element: item, update(job, {latest, retry}) {
            // Jobs without a picture (a check, a prompt) are one quiet line while they run, and nothing after.
            // A picture takes seconds: the same quiet line while it is made, then the picture.
            const card = VIDEOS.includes(job.kind || 'generate') || (job.kind === 'image' && !WORKING.includes(job.status));
            const next = card ? jobMode(job) + (jobMode(job) === 'done' ? `:${job.play}:${job.thumbnail}:${job.work}` : '')
                : WORKING.includes(job.status) ? 'quiet' : 'none';
            if (next !== mode) {
                mode = next; item.dataset.job = job.id; item.dataset.mode = next.split(':')[0]; item.hidden = next === 'none';
                if (next !== 'working') stopping.delete(job.id);
                if (next === 'working') apply = working(item, job);
                else if (next.startsWith('done')) apply = done(item, job);
                else if (next === 'quiet') { item.replaceChildren(el('span', 'fv-chat-dots'), el('span', null, t(...(QUIET[job.kind] || ['Working', '进行中'])))); apply = null; }
                else if (next === 'stopped') { item.replaceChildren(el('span', null, t('Stopped', '已停止'))); apply = null; }
                else if (next === 'failed') {
                    item.replaceChildren(el('span', null, t('Could not generate', '没有生成出来')));
                    // Trying again says the same sentence to the agent once more; why it failed is the agent's to say.
                    if (retry) item.append(press('fv-chat-retry', t('Retry', '重试'), retry));
                    apply = null;
                } else { item.replaceChildren(); apply = null; }
            }
            apply?.(job, latest);
            const again = item.querySelector('.fv-chat-retry'); if (again) again.disabled = !sendingAllowed();
        }};
    }
    function confirmCard() {
        const item = el('li', 'fv-chat-confirm');
        let shownState = null;
        return {element: item, update(entry) {
            const value = answers.get(entry.id) || state.confirms[entry.id] || entry.state || 'asked';
            if (value === shownState) return;
            shownState = value; item.dataset.state = value === 'asked' ? 'asked' : 'answered';
            if (value !== 'asked') { item.replaceChildren(el('span', null, value === 'approved' ? t('Started', '已开始') : t('Not now', '先不拍'))); return; }
            const answer = approve => async () => {
                item.querySelectorAll('button').forEach(button => { button.disabled = true; });
                try {
                    const response = await agentPost(api, '/freevideo/agent/chat/confirm', {id: entry.id, approve});
                    if (response.ok) answers.set(entry.id, (await response.json()).state || (approve ? 'approved' : 'declined'));
                } catch { /* The card stays as asked. */ }
                shownState = null; render(); poll();
            };
            const buttons = el('div', 'fv-chat-actions');
            buttons.append(press('fv-chat-yes fv-primary', t('Start', '开始'), answer(true)), press('fv-chat-no', t('Not now', '先不'), answer(false)));
            const question = el('p', null, entry.question);
            const estimate = el('p', 'fv-chat-meta', entry.estimate_seconds > 0 ? about(entry.estimate_seconds, t) : ''); estimate.hidden = !estimate.textContent;
            item.replaceChildren(question, estimate, buttons);
        }};
    }
    // Before anything is said: what the agent can do, and sentences that send themselves when clicked.
    function hello() {
        const item = el('li', 'fv-chat-hello');
        item.append(el('p', null, t('I can make videos for you,', '我可以替你生成视频，')), el('p', null, t('or turn a story into a short film.', '也可以把一个故事拍成短片。')));
        return {element: item, update() {}};
    }
    function examples() {
        const item = el('li', 'fv-chat-examples'), list = el('div');
        const lines = [t('Make a 10-second video: a rainy night, a girl squeezes onto the last bus', '生成一段 10 秒的视频：雨夜，女孩挤上末班车'),
            t('Make a 1-minute vertical short film: a day in a coffee shop', '做一条 1 分钟的竖屏短片：咖啡店的一天')];
        list.append(...lines.map(line => press(null, line, () => send(line))));
        item.append(el('p', 'fv-chat-meta', t('Try saying:', '可以这样说：')), list);
        return {element: item, update() { list.querySelectorAll('button').forEach(button => { button.disabled = !sendingAllowed(); }); }};
    }
    function dots() {
        const item = el('li', 'fv-chat-thinking'), mark = el('span', 'fv-chat-dots'); mark.append(el('i'), el('i'), el('i'));
        item.setAttribute('role', 'status'); item.setAttribute('aria-label', t('Thinking', '正在思考')); item.append(mark);
        return {element: item, update() {}};
    }
    const MAKE = {hello, examples, dots, user: () => message('user'), agent: () => message('agent'), job: jobCard, confirm: confirmCard};

    function render(follow = false) {
        const entries = chatEntries(state), ids = new Set(entries.map(entry => entry.id).filter(Boolean));
        pending = pending.filter(entry => !ids.has(entry.id));
        const said = entries.some(entry => entry.type !== 'message' || entry.role === 'user') || pending.length > 0;
        const finished = entries.filter(entry => entry.type === 'job' && state.jobs[entry.job]?.status === 'succeeded' && state.jobs[entry.job].work).at(-1);
        const wanted = [];
        if (!entries.length && !pending.length) wanted.push(['hello', 'hello', null]);
        let lastUser = null;
        for (const entry of entries) {
            if (entry.type === 'message') {
                if (entry.role === 'user') lastUser = entry;
                wanted.push([entry.role === 'user' && entry.id ? `m:${entry.id}` : `s:${entry.seq}`, entry.role === 'user' ? 'user' : 'agent', entry]);
            } else if (entry.type === 'job') {
                const job = state.jobs[entry.job]; if (!job) continue;
                const text = lastUser?.text;
                wanted.push([`s:${entry.seq}`, 'job', job, {latest: entry === finished, retry: text ? () => send(text) : null}]);
            } else wanted.push([`s:${entry.seq}`, 'confirm', entry]);
        }
        for (const entry of pending) wanted.push([`m:${entry.id}`, 'user', {...entry, taken: false}]);
        if (!said) wanted.push(['examples', 'examples', null]);
        // The agent has the sentence, or is waiting for one, and has not answered yet.
        const tail = pending.at(-1) || entries.at(-1);
        if (tail?.type !== 'job' && tail?.type !== 'confirm' && (pending.length || tail?.role === 'user') && state.agent.connected === true
            && (state.agent.listening !== false || tail.taken === true)) wanted.push(['dots', 'dots', null]);

        const stick = follow || pinned;
        const before = log.children.length, keep = new Set(wanted.map(([key]) => key));
        for (const [key, node] of nodes) if (!keep.has(key)) { node.element.remove(); nodes.delete(key); }
        wanted.forEach(([key, kind, value, extra], index) => {
            let node = nodes.get(key);
            if (!node) { node = MAKE[kind](); nodes.set(key, node); }
            node.update(value, extra || {});
            if (log.children[index] !== node.element) log.insertBefore(node.element, log.children[index] || null);
        });
        const sendable = sendingAllowed();
        input.disabled = state.agent.connected !== true || creating || !!selectedSession && selectedSession !== state.session;
        input.placeholder = state.agent.connected === true && !sendable ? t('Ask your agent to keep listening', '回到 Agent 那边让它继续') : t('Message the agent…', '对 Agent 说…');
        sendButton.disabled = !sendable || !input.value.trim();
        if (focusSession === state.session && focusSession && !input.disabled && active()) { focusSession = null; input.focus(); }
        if (stick) { pinned = true; scroller.scrollTop = scroller.scrollHeight; down.hidden = true; }
        else if (log.children.length > before) down.hidden = false;
    }
    scroller.addEventListener('scroll', () => {
        if (!scroller.clientHeight) return;
        pinned = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 48;
        if (pinned) down.hidden = true;
    }, {passive: true});

    async function readAway() {
        const row = state.current ? null : runningElsewhere(conversations, state.session);
        if (!row) { away = null; return; }
        try {
            // Past the last message: only that conversation's jobs come back.
            const query = new URLSearchParams({session: row.id, after: String(Number.MAX_SAFE_INTEGER)});
            const response = await agentGet(api, `/freevideo/agent/chat?${query}`, {signal: closed.signal});
            if (!response.ok) { away = null; return; }
            const data = await response.json(), jobs = Object.values(data.jobs || {}).filter(job => WORKING.includes(job?.status));
            const job = data.jobs?.[data.current] || jobs[0];
            away = job ? {session: row.id, job, ids: jobs.map(job => job.id)} : null;
        } catch { /* The last reading stays until the next one. */ }
    }
    let reportedJob = null;
    function report() {
        const current = (state.current ? state.jobs[state.current] : away?.job) || null;
        // A job that starts or ends changes a dot in the list, so the list is read again right away.
        if ((current?.id || null) !== reportedJob) { reportedJob = current?.id || null; void readConversations(true); }
        changed({known, agent: state.agent, current, fraction: current ? fractionOf(current) : 0, left: current ? leftOf(current) : null, active: state.active,
            any: state.items.size > 0 || pending.length > 0});
    }
    async function send(text) {
        text = String(text).trim();
        if (!text || !sendingAllowed()) return false;
        const sentSelection = selection;
        const entry = {id: newId(), text}; pending.push(entry); render(true); report();
        let response = null;
        const body = conversations.supported === true && state.session ? {...entry, session: state.session} : entry;
        try { response = await agentPost(api, '/freevideo/agent/chat', body); } catch { /* Handled below as not sent. */ }
        if (stopped) return false;
        if (response?.ok) {
            const value = await response.json().catch(() => ({}));
            if (sentSelection === selection) { if (value.agent) state.agent = value.agent; void poll(); }
            void readConversations(true); return true;
        }
        if (sentSelection !== selection) return false;
        // Not sent: the sentence goes back to the box. An agent that was never connected leads back to the card.
        pending = pending.filter(item => item !== entry);
        if (!input.value) { input.value = text; grow(); }
        if (response?.status === 409) state = {...state, agent: {connected: false, name: null}};
        render(); report();
        return false;
    }
    function grow() {
        input.style.height = 'auto';
        // At most five lines; the box scrolls after that.
        const line = parseFloat(getComputedStyle(input).lineHeight) || 22;
        input.style.height = `${Math.min(input.scrollHeight, Math.round(line * 5) + 14)}px`;
        sendButton.disabled = !sendingAllowed() || !input.value.trim();
    }
    input.addEventListener('input', grow);
    // Enter sends, Shift+Enter starts a new line; Enter that confirms an input-method candidate does neither.
    input.addEventListener('keydown', event => {
        if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
        event.preventDefault(); form.requestSubmit();
    });
    form.addEventListener('submit', event => {
        event.preventDefault();
        const text = input.value;
        if (!text.trim() || !sendingAllowed()) return;
        input.value = ''; grow(); void send(text);
    });

    // Both a server-side session change and a list selection reset the same reader. Job clocks stay keyed by job id.
    function resetChat() {
        state = emptyChat(); pending = []; answers.clear(); nodes.clear();
        log.querySelectorAll('video').forEach(video => video.pause()); log.replaceChildren(); pinned = true;
    }
    async function poll() {
        clearTimeout(timer); timer = null;
        if (stopped) return;
        if (busy) { reread = true; return; }
        if (!active()) return;
        busy = true; reread = false;
        void readConversations();
        const readSelection = selection, requested = selectedSession;
        let again = false;
        try {
            const after = state.session && (!requested || requested === state.session) ? state.last : 0;
            const query = new URLSearchParams();
            if (requested) query.set('session', requested);
            if (after) query.set('after', String(after));
            const response = await agentGet(api, '/freevideo/agent/chat' + (query.size ? `?${query}` : ''), {signal: closed.signal});
            if (stopped) return;
            if (readSelection !== selection) again = true;
            else if (response.ok) {
                const data = await response.json();
                if (stopped) return;
                if (readSelection !== selection) { again = true; }
                // Another conversation began: forget this one and read the new one whole.
                else if (after && (data.session ?? null) !== state.session) { resetChat(); again = true; }
                else {
                    if ((data.session ?? null) !== state.session) resetChat();
                    state = chatMerge(state, data); failures = 0;
                    conversations = selectConversation(conversations, state.session); renderConversations();
                    await readAway();
                    if (stopped) return;
                    if (readSelection !== selection) { away = null; again = true; }
                }
            } else if (response.status === 404 && requested) {
                selectedSession = undefined; selection++; resetChat(); again = true; void readConversations(true);
            } else failures++;
        } catch { failures++; }
        finally { busy = false; }
        if (stopped) return;
        if (again || reread) return poll();
        known = true;
        // The next read is booked before the page hears of this one, so the page's sync() does not start another.
        const idle = state.agent.connected !== true && !state.active;
        timer = setTimeout(poll, (idle ? Math.max(interval, 3000) : interval) * Math.min(4, 1 + failures));
        render(); report();
    }
    // Between reads the estimate keeps moving, on the cards and in the page's header alike.
    const moving = setInterval(() => {
        if (!active() || ![...Object.values(state.jobs), ...(away ? [away.job] : [])].some(job => job.status === 'running')) return;
        for (const item of log.children) item.tick?.();
        report();
    }, 250);
    const visible = () => { if (!document.hidden) sync(); };
    document.addEventListener('visibilitychange', visible);
    function sync() {
        if (pinned) scroller.scrollTop = scroller.scrollHeight;
        if (active() && !timer && !busy) poll();
    }
    render();
    return {element, input, sync, refresh: poll,
        scrollToJob(id) {
            // A job of another conversation: go to that conversation, which opens at its end where the job is.
            if (away?.job.id === id && !state.jobs[id]) chooseChat(away.session);
            else log.querySelector(`[data-job="${CSS.escape(id)}"]`)?.scrollIntoView({block: 'center', behavior: 'smooth'});
        },
        async stopAll() {
            const ids = [...new Set([...Object.values(state.jobs).filter(job => WORKING.includes(job.status)).map(job => job.id), ...(away?.ids || [])])];
            ids.forEach(id => stopping.add(id)); render();
            await Promise.allSettled(ids.map(id => agentPost(api, '/freevideo/agent/activity/cancel', {id})));
            poll();
        },
        stop() { stopped = true; closed.abort(); clearInterval(moving); clearTimeout(timer); timer = null;
            document.removeEventListener('visibilitychange', visible); document.removeEventListener('pointerdown', outside, true);
            document.removeEventListener('keydown', keys, true); window.removeEventListener('resize', resize);
            log.querySelectorAll('video').forEach(video => video.pause()); }};
}
