import { redirectTokenMutationGet, runTokenMutation } from "../mutation-route";

type RouteContext = {
    params: Promise<{ tokenId: string }>;
};

export async function POST(request: Request, context: RouteContext) {
    return runTokenMutation(request, context, "delete");
}

export function GET() {
    redirectTokenMutationGet();
}
