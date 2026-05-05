"""Module E: Share Engine — generate shareable trade result cards for X/Twitter."""


def generate_share_card(trade: dict, user_address: str) -> dict:
    """Generate share card text for a resolved trade."""
    symbol = trade.get("token_symbol", "???")
    pnl_pct = trade.get("pnl_pct", 0) or 0
    short_addr = user_address[:6] + "..." + user_address[-4:] if len(user_address) > 10 else user_address

    if pnl_pct > 0:
        card_type = "WIN"
        emoji = "🚀"
        text = f"🦍 APED ${symbol} → +{pnl_pct:.1f}% {emoji}\n\nTrading IQ: over 9000\n— {short_addr} on Ape or Fade"
    elif pnl_pct < 0:
        card_type = "REKT"
        emoji = "💀"
        text = f"💀 APED ${symbol} → {pnl_pct:.1f}%\n\nThe Oracle warned me. 😭\n— {short_addr} on Ape or Fade"
    else:
        card_type = "STREAK"
        emoji = "🔥"
        text = f"🔥 Flat on ${symbol} — living to trade another day\n— {short_addr} on Ape or Fade"

    # Check for streak
    streak = trade.get("streak", 0)
    if streak and streak >= 3:
        card_type = "STREAK"
        emoji = "🔥"
        text = f"🔥 {streak}-day win streak on Ape or Fade!\n\nCertified Degen Status 🧠\n— {short_addr}"

    hashtags = ["#ApeOrFade", "#InitiaSignal", "#OnChainDegen"]
    share_url = f"https://apeorfade.xyz?ref={user_address[:8]}"

    return {
        "text": text,
        "emoji": emoji,
        "hashtags": hashtags,
        "share_url": share_url,
        "card_type": card_type,
    }
