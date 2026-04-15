// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Strings.sol";
import "@openzeppelin/contracts/utils/Base64.sol";

contract ProofOfAlpha is ERC721, Ownable {
    using Strings for uint256;

    enum Tier { BRONZE_APE, SILVER_APE, GOLD_APE, DIAMOND_HANDS, SIGNAL_SAGE }

    struct Achievement {
        Tier tier;
        uint256 wins;
        uint256 winRate; // basis points (e.g. 7500 = 75%)
        uint256 bestStreak;
        uint256 mintedAt;
    }

    uint256 private _nextTokenId;
    mapping(uint256 => Achievement) public achievements;
    mapping(address => mapping(Tier => bool)) public hasTier;
    mapping(address => bool) public authorizedMinters;

    // Tier thresholds
    uint256 public constant BRONZE_WINS = 10;
    uint256 public constant SILVER_RATE = 5000;  // 50%
    uint256 public constant SILVER_MIN_TRADES = 50;
    uint256 public constant GOLD_WINS = 100;
    uint256 public constant DIAMOND_STREAK = 10;
    uint256 public constant SAGE_RATE = 8000;    // 80%

    event AchievementMinted(address indexed to, uint256 tokenId, Tier tier);

    constructor() ERC721("Proof of Alpha", "ALPHA") Ownable(msg.sender) {}

    function mintAchievement(
        address to,
        Tier tier,
        uint256 wins,
        uint256 winRate,
        uint256 bestStreak
    ) external returns (uint256) {
        require(authorizedMinters[msg.sender] || msg.sender == owner(), "Not authorized");
        require(!hasTier[to][tier], "Already has tier");

        uint256 tokenId = _nextTokenId++;
        achievements[tokenId] = Achievement(tier, wins, winRate, bestStreak, block.timestamp);
        hasTier[to][tier] = true;
        _mint(to, tokenId);
        emit AchievementMinted(to, tokenId, tier);
        return tokenId;
    }

    // Soulbound: block all transfers
    function _update(address to, uint256 tokenId, address auth) internal override returns (address) {
        address from = _ownerOf(tokenId);
        require(from == address(0) || to == address(0), "Soulbound: non-transferable");
        return super._update(to, tokenId, auth);
    }

    function tokenURI(uint256 tokenId) public view override returns (string memory) {
        _requireOwned(tokenId);
        Achievement memory a = achievements[tokenId];
        string memory tierName = _tierName(a.tier);
        string memory tierEmoji = _tierEmoji(a.tier);

        string memory svg = string(abi.encodePacked(
            '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" style="background:#0e0e0e">',
            '<text x="200" y="80" text-anchor="middle" font-size="48" fill="#8eff71">', tierEmoji, '</text>',
            '<text x="200" y="140" text-anchor="middle" font-size="24" fill="#fff" font-family="monospace">', tierName, '</text>',
            '<text x="200" y="200" text-anchor="middle" font-size="16" fill="#adaaaa" font-family="monospace">Wins: ', a.wins.toString(), '</text>',
            '<text x="200" y="230" text-anchor="middle" font-size="16" fill="#adaaaa" font-family="monospace">Win Rate: ', (a.winRate / 100).toString(), '%</text>',
            '<text x="200" y="260" text-anchor="middle" font-size="16" fill="#adaaaa" font-family="monospace">Best Streak: ', a.bestStreak.toString(), '</text>',
            '<text x="200" y="340" text-anchor="middle" font-size="12" fill="#494847" font-family="monospace">PROOF OF ALPHA | KINETIC</text>',
            '</svg>'
        ));

        string memory json = string(abi.encodePacked(
            '{"name":"', tierName, '","description":"Soulbound Proof of Alpha - KINETIC",',
            '"image":"data:image/svg+xml;base64,', Base64.encode(bytes(svg)), '",',
            '"attributes":[{"trait_type":"Tier","value":"', tierName, '"},',
            '{"trait_type":"Wins","value":', a.wins.toString(), '},',
            '{"trait_type":"Win Rate","value":', (a.winRate / 100).toString(), '},',
            '{"trait_type":"Best Streak","value":', a.bestStreak.toString(), '}]}'
        ));

        return string(abi.encodePacked("data:application/json;base64,", Base64.encode(bytes(json))));
    }

    function setAuthorizedMinter(address minter, bool authorized) external onlyOwner {
        authorizedMinters[minter] = authorized;
    }

    function _tierName(Tier t) internal pure returns (string memory) {
        if (t == Tier.BRONZE_APE) return "Bronze Ape";
        if (t == Tier.SILVER_APE) return "Silver Ape";
        if (t == Tier.GOLD_APE) return "Gold Ape";
        if (t == Tier.DIAMOND_HANDS) return "Diamond Hands";
        return "Signal Sage";
    }

    function _tierEmoji(Tier t) internal pure returns (string memory) {
        if (t == Tier.BRONZE_APE) return unicode"🥉";
        if (t == Tier.SILVER_APE) return unicode"🥈";
        if (t == Tier.GOLD_APE) return unicode"🥇";
        if (t == Tier.DIAMOND_HANDS) return unicode"💎";
        return unicode"🧠";
    }
}
