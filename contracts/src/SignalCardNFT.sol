// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Base64} from "@openzeppelin/contracts/utils/Base64.sol";
import {Strings} from "@openzeppelin/contracts/utils/Strings.sol";

/// @title SignalCardNFT — AI-curated trading cards as on-chain LP recipes
/// @notice Each token stores a CardData struct with pre-computed v4 ticks.
///         Minting gated to `minter` (backend). Play-marking gated to `hook`.
contract SignalCardNFT is ERC721, Ownable {
    using Strings for uint256;
    using Strings for int256;

    struct CardData {
        string tokenSymbol;
        int24 stopTickHint;    // tickLower for APE cards
        int24 targetTickHint;  // tickUpper for APE cards
        uint16 riskScore;      // 0-100 → drives dynamic fee
        uint8 rarity;          // 0=Common 1=Rare 2=Epic 3=Legendary 4=Mythic
        bool isBull;           // APE=true, FADE=false
        uint64 expiresAt;
        bool played;
    }

    address public minter;
    address public hook;
    mapping(uint256 => CardData) public cards;

    event CardMinted(uint256 indexed cardId, address indexed to, string symbol);
    event CardPlayed(uint256 indexed cardId);

    error NotMinter();
    error NotHook();
    error AlreadyPlayed();

    constructor(address _minter, address _owner) ERC721("Kinetic Signal Card", "KSC") Ownable(_owner) {
        minter = _minter;
    }

    function setMinter(address _m) external onlyOwner { minter = _m; }
    function setHook(address _h) external onlyOwner { hook = _h; }

    function mint(uint256 cardId, address to, CardData calldata d) external {
        if (msg.sender != minter) revert NotMinter();
        cards[cardId] = d;
        _mint(to, cardId);
        emit CardMinted(cardId, to, d.tokenSymbol);
    }

    function markPlayed(uint256 cardId) external {
        if (msg.sender != hook) revert NotHook();
        if (cards[cardId].played) revert AlreadyPlayed();
        cards[cardId].played = true;
        emit CardPlayed(cardId);
    }

    function cardData(uint256 cardId) external view returns (CardData memory) {
        return cards[cardId];
    }

    function tokenURI(uint256 cardId) public view override returns (string memory) {
        _requireOwned(cardId);
        CardData memory c = cards[cardId];
        string memory r = _rarityName(c.rarity);
        string memory svg = string.concat(
            '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="480">',
            '<rect width="320" height="480" fill="#0a0a0a"/>',
            '<text x="160" y="60" fill="#8eff71" font-size="28" text-anchor="middle" font-family="monospace">', c.tokenSymbol, '</text>',
            '<text x="160" y="100" fill="#bf81ff" font-size="14" text-anchor="middle">', r, '</text>',
            '<text x="160" y="240" fill="#fff" font-size="20" text-anchor="middle">', c.isBull ? "APE" : "FADE", '</text>',
            '<text x="160" y="300" fill="#aaa" font-size="12" text-anchor="middle">[', _itoa(c.stopTickHint), ' -> ', _itoa(c.targetTickHint), ']</text>',
            '<text x="160" y="340" fill="#aaa" font-size="11" text-anchor="middle">risk ', uint256(c.riskScore).toString(), '/100</text>',
            '</svg>'
        );
        string memory json = string.concat(
            '{"name":"', c.tokenSymbol, ' ', r, ' #', cardId.toString(),
            '","image":"data:image/svg+xml;base64,', Base64.encode(bytes(svg)), '"}'
        );
        return string.concat("data:application/json;base64,", Base64.encode(bytes(json)));
    }

    function _rarityName(uint8 r) internal pure returns (string memory) {
        if (r == 1) return "Rare";
        if (r == 2) return "Epic";
        if (r == 3) return "Legendary";
        if (r == 4) return "Mythic";
        return "Common";
    }

    function _itoa(int24 v) internal pure returns (string memory) {
        if (v < 0) return string.concat("-", uint256(uint24(-v)).toString());
        return uint256(uint24(v)).toString();
    }
}
