// The list is a server snapshot, in the server's order. An unsaid current conversation need not be in it.
export const emptyConversations = () => ({supported: null, current: null, conversations: []});
export const selectConversation = (state, session) => ({...state, current: session ?? null});
export const hasConversations = state => state.supported === true && state.conversations.length > 0;
// The first other conversation with work under way; null when there is none.
export const runningElsewhere = (state, session) => state.conversations.find(row => row.running > 0 && row.id !== session) || null;

export function mergeConversations(state, data, status = 200) {
    // A legacy server is probed once per page; ordinary errors retain the last good snapshot.
    if (status === 404) return {...state, supported: false, conversations: []};
    if (state.supported === false || status !== 200 || !Array.isArray(data?.conversations)) return state;
    const seen = new Set(), conversations = [];
    for (const row of data.conversations) {
        if (typeof row?.id !== 'string' || !row.id || typeof row.title !== 'string' || !row.title.trim() || seen.has(row.id)) continue;
        seen.add(row.id);
        conversations.push({id: row.id, title: row.title, updated_at: row.updated_at,
            running: Math.max(0, Math.floor(Number(row.running) || 0))});
        if (conversations.length === 50) break;
    }
    return {...state, supported: true, conversations};
}
