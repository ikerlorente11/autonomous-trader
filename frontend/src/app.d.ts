declare global {
	namespace App {
		interface Error {
			code?: string;
			message: string;
		}
		// interface Locals {}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
