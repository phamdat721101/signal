# Design System Document: The Kinetic Terminal

## 1. Overview & Creative North Star: "The Kinetic Terminal"
This design system is built to capture the high-stakes, high-velocity energy of Web3 trading. The Creative North Star is **The Kinetic Terminal**—an aesthetic that blends the raw authority of a Bloomberg terminal with the neon-drenched futurism of a cyberpunk HUD. 

To move beyond "standard" mobile layouts, this system utilizes **Intentional Asymmetry** and **Tonal Depth**. We reject the "flat" web. Instead, we treat the mobile screen as a deep space where elements float, overlap, and pulse. Information density is high, but legibility is maintained through aggressive typographic scale contrasts and a "glass-on-glass" layering philosophy.

---

## 2. Colors: High-Voltage Contrast
The palette is rooted in a "Pure Void" background, allowing neon accents to act as functional light sources.

### Core Palette
- **Background (`#0e0e0e`)**: The foundation. A deep, non-distracting void.
- **Primary / Ape (`#8eff71`)**: Use for "Success," "Longing," and "Ape-in" actions. It should feel radioactive.
- **Tertiary / Fade (`#ff7166`)**: Use for "Danger," "Shorting," and "Liquidation" risks. High urgency.
- **Secondary / ZK-AI (`#bf81ff`)**: Reserved for advanced tech features, AI insights, and zero-knowledge proofs.

### The "No-Line" Rule
**Explicit Instruction:** 1px solid borders for sectioning are strictly prohibited. Boundaries must be defined through background color shifts.
- Use `surface-container-low` for large section backgrounds.
- Use `surface-container-highest` for nested interactive elements.
- Transitions must feel seamless, like light hitting different depths of a dark pool.

### The "Glass & Gradient" Rule
To achieve "The Kinetic Terminal" look, main Action buttons and Hero cards should utilize a **Signature Texture**:
- **Gradient Flow:** Transition from `primary` (#8eff71) to `primary-container` (#2ff801) at a 135-degree angle.
- **Glow States:** Interactive elements in a "Success" state should have a 12px outer glow using `primary` at 20% opacity.

---

## 3. Typography: Editorial Data
We pair the geometric aggression of **Space Grotesk** with the utilitarian clarity of **Inter**.

- **Display (Space Grotesk, Bold):** Used for massive gains, ROI percentages, and "Ape" headlines. This is your "loudest" voice.
- **Headline (Space Grotesk, Medium):** Used for section titles.
- **Body (Inter, Regular):** Used for descriptions and tooltips.
- **Label/Mono (Inter, Semi-Bold):** Used for all on-chain data, wallet addresses, and gas fees. High-contrast labels ensure data is never misread.

**Editorial Tip:** Use "Display-LG" for critical numbers (e.g., +420%) and "Label-SM" for the metric title (e.g., 24H CHANGE) positioned immediately above it to create a sophisticated, unbalanced hierarchy.

---

## 4. Elevation & Depth: Tonal Layering
Traditional shadows are too "soft" for this aesthetic. We use **Tonal Layering** and **Glassmorphism**.

### The Layering Principle
Stacking defines priority:
1. **Base Layer:** `surface` (#0e0e0e).
2. **Section Layer:** `surface-container-low` (#131313).
3. **Card Layer:** `surface-container-highest` (#262626).
4. **Active/Floating Layer:** Glassmorphism (Surface color @ 60% opacity + 16px Backdrop Blur).

### Ambient Shadows & Ghost Borders
- **Shadows:** Only for floating modals. Use `on-surface` color at 6% opacity with a 32px blur.
- **Ghost Borders:** If an element feels "lost," use the `outline-variant` token at **15% opacity**. It should be a suggestion of a border, not a fence.

---

## 5. Components: Tactile High-Energy

### Buttons
- **Primary (Ape):** High-fill `primary`. Square corners (`DEFAULT: 0.25rem`). When pressed, it emits a `primary_dim` glow.
- **Secondary (Fade):** Ghost style. `outline` border at 40% opacity with `tertiary` text.
- **Tactile Feedback:** All buttons use a subtle inner-shadow on top (1px, 20% white) to create a "mechanical switch" feel.

### Cards & Lists
- **Rule:** Forbid divider lines. Use `surface-container-low` for the list track and `surface-container-high` for individual list items.
- **Spacing:** Use 12px (`xl` roundedness) for the main container and 8px (`lg`) for inner elements to create a nested, "fitted" appearance.

### The "De-Fi" Pulse (Custom Component)
- **The Pulse:** Any active trade or live "Ape" position should have a soft, rhythmic opacity pulse (100% to 70%) on its `primary_container` background to signal "live" data.

### Inputs
- **Text Inputs:** No bottom line. Use a solid `surface-container-highest` background. The cursor should be the `primary` neon green, mimicking a terminal command line.

---

## 6. Do’s and Don’ts

### Do
- **DO** use heavy typographic weight for data. Numbers are the hero.
- **DO** overlap elements (e.g., a "Buy" button floating 8px over a chart's edge) to create depth.
- **DO** use `secondary` (purple) exclusively for AI-generated tips or ZK-privacy features to distinguish "Machine Intelligence" from "User Action."

### Don’t
- **DON'T** use pure white (`#FFFFFF`) for body text. Use `on-surface-variant` (#adaaaa) to reduce eye strain in dark mode.
- **DON'T** use rounded corners larger than `xl` (0.75rem). This system is sharp, precision-engineered, and aggressive; excessive rounding kills the "Degen" energy.
- **DON'T** use standard Material shadows. If it doesn't look like a glowing screen in a dark room, it’s too "corporate."