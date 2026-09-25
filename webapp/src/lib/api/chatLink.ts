import { apiUrl } from '$lib/api/base';
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
	mode:
		| 'connect_group'
		| 'group_connected'
		| 'already_member'
		| 'resident_address'
		| 'personal_address'
		| 'not_member'
		| 'no_chat';
	token?: string | null;
	admin_link?: string | null;
	chats: ChatOption[];
};

async function authenticatedHeaders(): Promise<HeadersInit> {
	return {
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
	const response = await fetch(
		`${apiUrl('/chat-link/addresses/search')}?q=${encodeURIComponent(q)}`
	);
	return (await json<{ items: AddressOption[] }>(response)).items;
}

export type PostalAddressPage = {
	items: AddressOption[];
	total: number;
};

export async function postalAddresses(
	code: string,
	q = '',
	offset = 0
): Promise<PostalAddressPage> {
	const params = new URLSearchParams({ code, q, offset: String(offset) });
	const response = await fetch(
		`${apiUrl('/chat-link/addresses/postal')}?${params}`
	);
	return json<PostalAddressPage>(response);
}

export async function nearestAddresses(
	lat: number,
	lon: number
): Promise<AddressOption[]> {
	const response = await fetch(
		`${apiUrl('/chat-link/addresses/nearest')}?lat=${lat}&lon=${lon}`
	);
	return (await json<{ items: AddressOption[] }>(response)).items;
}

export async function selectAddress(
	addressId: number,
	targetChatId: number | null = null,
	residentChatId: number | null = null
): Promise<SelectResult> {
	return json(
		await fetch(apiUrl('/chat-link/select'), {
			method: 'POST',
			headers: await authenticatedHeaders(),
			body: JSON.stringify({
				address_id: addressId,
				chat_id: targetChatId,
				resident_chat_id: residentChatId
			})
		})
	);
}

/** The selected home, not the device's current geolocation. */
export async function fetchResidence(
	signal?: AbortSignal
): Promise<AddressOption | null> {
	const response = await fetch(apiUrl('/chat-link/residence'), {
		headers: await authenticatedHeaders(),
		signal
	});
	return (await json<{ address: AddressOption | null }>(response)).address;
}
