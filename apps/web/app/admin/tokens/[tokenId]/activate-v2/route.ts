import { redirectTokenMutationGet, runTokenMutation } from "../mutation-route";

type Params = {
    params: Promise<{ tokenId: string }>;
};

export async function POST(request: Request, context: Params) {
    return runTokenMutation(request, context, "activate-v2");
}

export function GET() {
    return redirectTokenMutationGet();
}
