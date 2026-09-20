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
	mode: 'existing_chat' | 'connect_group';
	token: string;
	admin_link?: string | null;
	chats: ChatOption[];
};

async function headers(): Promise<HeadersInit> {
	return {
		'X-Max-User-Id': String(await waitForMaxUserId()),
		'Content-Type': 'application/json',
		'ngrok-skip-browser-warning': 'true'
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
		headers: await headers()
	});
	return (await json<{ items: AddressOption[] }>(response)).items;
}

export async function nearestAddresses(lat: number, lon: number): Promise<AddressOption[]> {
	const response = await fetch(`/api/chat-link/addresses/nearest?lat=${lat}&lon=${lon}`, {
		headers: await headers()
	});
	return (await json<{ items: AddressOption[] }>(response)).items;
}

export async function selectAddress(addressId: number): Promise<SelectResult> {
	return json(
		await fetch('/api/chat-link/select', {
			method: 'POST',
			headers: await headers(),
			body: JSON.stringify({ address_id: addressId })
		})
	);
}
