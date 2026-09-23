export type ChatLinkKind = 'map' | 'text';
export type ChatLinkMode =
	| 'chat_link_map'
	| 'chat_link_text'
	| `chat_link_map_bind_${number}`
	| `chat_link_text_bind_${number}`
	| `chat_link_map_resident_${number}`
	| `chat_link_text_resident_${number}`;

export type ParsedChatLinkMode = {
	value: ChatLinkMode;
	mode: ChatLinkKind;
	targetChatId: number | null;
	residentChatId: number | null;
};

const ACTIVE_MODE_KEY = 'chat-link-active-mode-v1';
const ACTIVE_MODE_TTL_MS = 30 * 60 * 1000;

type StoredMode = {
	mode: ChatLinkMode;
	savedAt: number;
};

export function buildChatLinkMode(
	mode: ChatLinkKind,
	targetChatId: number | null,
	residentChatId: number | null = null
): ChatLinkMode {
	if (residentChatId !== null) return `chat_link_${mode}_resident_${residentChatId}` as ChatLinkMode;
	if (targetChatId === null) return `chat_link_${mode}` as ChatLinkMode;
	return `chat_link_${mode}_bind_${targetChatId}` as ChatLinkMode;
}

export function parseChatLinkMode(value: string | null): ParsedChatLinkMode | null {
	if (value === 'chat_link_map') {
		return { value, mode: 'map', targetChatId: null, residentChatId: null };
	}
	if (value === 'chat_link_text') {
		return { value, mode: 'text', targetChatId: null, residentChatId: null };
	}
	if (!value) return null;

	const match = /^chat_link_(map|text)_(bind|resident)_(-?\d+)$/.exec(value);
	if (!match) return null;
	const chatId = Number(match[3]);
	if (!Number.isSafeInteger(chatId)) return null;
	return {
		value: value as ChatLinkMode,
		mode: match[1] as ChatLinkKind,
		targetChatId: match[2] === 'bind' ? chatId : null,
		residentChatId: match[2] === 'resident' ? chatId : null
	};
}

export function isChatLinkMode(value: string | null): value is ChatLinkMode {
	return parseChatLinkMode(value) !== null;
}

export function loadActiveChatLinkMode(): ChatLinkMode | null {
	try {
		const raw = localStorage.getItem(ACTIVE_MODE_KEY);
		if (!raw) return null;
		const stored = JSON.parse(raw) as StoredMode;
		if (!isChatLinkMode(stored.mode) || Date.now() - stored.savedAt > ACTIVE_MODE_TTL_MS) {
			localStorage.removeItem(ACTIVE_MODE_KEY);
			return null;
		}
		return stored.mode;
	} catch {
		return null;
	}
}

export function saveActiveChatLinkMode(mode: ChatLinkMode): void {
	try {
		localStorage.setItem(ACTIVE_MODE_KEY, JSON.stringify({ mode, savedAt: Date.now() }));
	} catch {
		// WebView может запрещать storage; flow продолжит работать без восстановления.
	}
}

export function clearActiveChatLinkMode(): void {
	try {
		localStorage.removeItem(ACTIVE_MODE_KEY);
	} catch {
		// WebView может запрещать storage.
	}
}
