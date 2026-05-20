import { analyzeTokenAction, deleteRevokedTokenAction, resetTokenAction, revokeTokenAction } from "./actions";

export function TokenActions({ tokenId, status }: { tokenId: string; status: string }) {
    const isRevoked = status === "revoked";

    return (
        <div className="row" style={{ justifyContent: "flex-end" }}>
            <form action={analyzeTokenAction}>
                <input type="hidden" name="tokenId" value={tokenId} />
                <button className="button secondary" type="submit" disabled={isRevoked}>Analyze</button>
            </form>
            <form action={resetTokenAction}>
                <input type="hidden" name="tokenId" value={tokenId} />
                <button className="button secondary" type="submit">Reset</button>
            </form>
            <form action={revokeTokenAction}>
                <input type="hidden" name="tokenId" value={tokenId} />
                <button className="button danger" type="submit" disabled={isRevoked}>Revoke</button>
            </form>
            {isRevoked && (
                <form action={deleteRevokedTokenAction}>
                    <input type="hidden" name="tokenId" value={tokenId} />
                    <button className="button danger" type="submit">Delete</button>
                </form>
            )}
        </div>
    );
}
