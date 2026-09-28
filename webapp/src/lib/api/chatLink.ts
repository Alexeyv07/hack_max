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
				resident_chat_id: residentChatId,
				onboarding: true
			})
		})
	);
}

export async function navigateChatLink(action: 'home' | 'choose_address'): Promise<void> {
	const response = await fetch(apiUrl('/chat-link/navigation'), {
		method: 'POST',
		headers: await authenticatedHeaders(),
		body: JSON.stringify({ action })
	});
	if (!response.ok) {
		const data = await response.json().catch(() => ({}));
		throw new Error(data.detail || `HTTP ${response.status}`);
	}
}

async function adminPost<T>(path: string, body: object, noContent = false): Promise<T> {
	const response = await fetch(apiUrl(`/chat-link/admin/${path}`), {
		method: 'POST',
		headers: await authenticatedHeaders(),
		body: JSON.stringify(body)
	});
	if (noContent) {
		if (!response.ok) {
			const data = await response.json().catch(() => ({}));
			throw new Error(data.detail || `HTTP ${response.status}`);
		}
		return undefined as T;
	}
	return json<T>(response);
}

export function showAdminInvitation(addressId: number, token: string): Promise<void> {
	return adminPost('invitation', { address_id: addressId, token }, true);
}

export function backToNoChat(addressId: number): Promise<void> {
	return adminPost('back', { address_id: addressId }, true);
}

export async function checkAdminGroups(addressId: number): Promise<ChatOption[]> {
	const data = await adminPost<{ items: ChatOption[] }>('check', { address_id: addressId });
	return data.items;
}

export function confirmAdminGroup(addressId: number, chatId: number): Promise<ChatOption> {
	return adminPost('confirm', { address_id: addressId, chat_id: chatId });
}

export type ResidenceResponse = {
	address: AddressOption | null;
	addresses: AddressOption[];
};

/** Selected nearby home plus every current address from «Мои адреса». */
export async function fetchResidence(signal?: AbortSignal): Promise<ResidenceResponse> {
	const response = await fetch(apiUrl('/chat-link/residence'), {
		headers: await authenticatedHeaders(),
		signal
	});
	return json<ResidenceResponse>(response);
}
