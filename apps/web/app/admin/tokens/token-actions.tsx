import { analyzeTokenAction, resetTokenAction, revokeTokenAction } from "./actions";

export function TokenActions({ tokenId, disabled }: { tokenId: string; disabled?: boolean }) {
    return (
        <div className="row" style={{ justifyContent: "flex-end" }}>
            <form action={analyzeTokenAction}>
                <input type="hidden" name="tokenId" value={tokenId} />
                <button className="button secondary" type="submit">Analyze</button>
            </form>
            <form action={resetTokenAction}>
                <input type="hidden" name="tokenId" value={tokenId} />
                <button className="button secondary" type="submit">Reset</button>
            </form>
            <form action={revokeTokenAction}>
                <input type="hidden" name="tokenId" value={tokenId} />
                <button className="button danger" type="submit" disabled={disabled}>Revoke</button>
            </form>
        </div>
    );
}