import { waitForMaxUserId } from '$lib/maxUser';

export type AddressOption = {
	id: number;
	address_text: string;
	latitude: number;
	longitude: number;
	score?: number | null;
};

export type ChatOption = {
	chat_id: number;
	title: string;
	invite_link?: string | null;
};

export type SelectResult = {
	address: AddressOption;
	mode: 'existing_chat' | 'connect_group' | 'group_connected' | 'approval_pending';
	token?: string | null;
	admin_link?: string | null;
	chats: ChatOption[];
};

const publicHeaders: HeadersInit = {
	'ngrok-skip-browser-warning': 'true'
};

async function authenticatedHeaders(): Promise<HeadersInit> {
	return {
		...publicHeaders,
		'X-Max-User-Id': String(await waitForMaxUserId()),
		'Content-Type': 'application/json'
	};
}

async function json<T>(response: Response): Promise<T> {
	if (!response.ok) {
		const data = await response.json().catch(() => ({}));
		throw new Error(data.detail || `HTTP ${response.status}`);
	}
	return response.json() as Promise<T>;
}

export async function searchAddresses(q: string): Promise<AddressOption[]> {
	const response = await fetch(`/api/chat-link/addresses/search?q=${encodeURIComponent(q)}`, {
		headers: publicHeaders
	});
	return (await json<{ items: AddressOption[] }>(response)).items;
}

export async function nearestAddresses(lat: number, lon: number): Promise<AddressOption[]> {
	const response = await fetch(`/api/chat-link/addresses/nearest?lat=${lat}&lon=${lon}`, {
		headers: publicHeaders
	});
	return (await json<{ items: AddressOption[] }>(response)).items;
}

export async function selectAddress(
	addressId: number,
	targetChatId: number | null = null
): Promise<SelectResult> {
	return json(
		await fetch('/api/chat-link/select', {
			method: 'POST',
			headers: await authenticatedHeaders(),
			body: JSON.stringify({ address_id: addressId, chat_id: targetChatId })
		})
	);
}
