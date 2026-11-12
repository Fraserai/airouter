# Model Router branded landing page QA

source visual truth: `/private/var/folders/fh/38g01_wx3fz8fksn_qt7df5w0000gn/T/TemporaryItems/com.apple.Photos.NSItemProvider/uuid=89541D62-2EC5-44C3-98CA-2635E5F5A441&code=001&library=1&type=1&mode=1&loc=true&cap=true.png/Orange Minimalist Creative Studio Logo - 1.png`
implementation: `http://127.0.0.1:8109/`
implementation screenshot: browser-rendered in the Codex in-app browser at the implementation URL
source pixels: 2000 x 2000
implementation viewport: 838 x 787 CSS px (browser capture)
density normalization: the supplied 2000 x 2000 artwork is rendered with `background-size: cover`; the implementation capture is a CSS viewport capture, so the source is judged for crop, palette and logo treatment rather than one-to-one pixel scale.
state: default landing page, no interaction active

## Comparison evidence

The source artwork is a cyan-to-lime-to-yellow field with a centered white
“model router” wordmark. The implementation separates those two roles: the
supplied artwork is used to derive a clean full-page gradient field, and the
supplied wordmark is extracted into a transparent lockup used in the navigation.
The centered duplicate wordmark is removed from behind the hero copy. The
browser capture showed the same palette, logo treatment and full-bleed crop at
the desktop viewport.

Focused checks covered the navigation links, hero CTA, model-pool link, footer
links, supplied PNG response, and the mobile breakpoint rules in the rendered
HTML. The page has no custom SVG, CSS-drawn logo, replacement gradient or
placeholder brand asset.

## Required fidelity surfaces

- Fonts and typography: system sans fallback, strong display scale, tighter
  tracking for the wordmark and headline, and responsive wrapping at 650px.
- Spacing and layout rhythm: padded navigation, separated hero actions, and a
  footer that collapses vertically on narrow screens.
- Colors and visual tokens: the supplied artwork provides the cyan, green and
  yellow palette; dark navy action controls and a translucent navy panel keep
  white copy readable without covering the brand image completely.
- Image quality and asset fidelity: the user-supplied 2000px PNG is served
  unchanged at `/brand/model-router-gradient-logo.png` and used as the actual
  page background.
- Copy and content: “More intelligence. Less cost.” and the direct routing
  explanation describe the current Model Router product scope; links point to the real API
  docs, catalog, dashboard and health endpoints.

## Findings

No actionable P0, P1 or P2 findings remain after the rendered pass.

## Comparison history

The first rendered pass exposed a P2 composition issue: the flattened source
image was used directly as the background while the page also rendered a
navigation wordmark, leaving a second large “model router” behind the hero copy.
The fix separated the supplied artwork into a clean raster gradient and a
transparent wordmark lockup, then placed the lockup in the navigation. The
post-fix browser capture shows one logo in the header and no duplicate wordmark
behind the hero.

The copy pass then removed the filler signal pills and replaced the vague
eyebrow, lede and footer with direct language about one API routing work across
the model pool.

## Open questions

- The supplied asset combines the gradient and wordmark in one raster. If a
  transparent standalone logo lockup becomes available, it can replace the
  textual navigation wordmark while keeping this background treatment.
- The mockup did not specify a separate mobile composition; the implementation
  uses a compact responsive layout and keeps all primary actions available.

## Implementation checklist

- [x] Use supplied artwork as the real page background.
- [x] Use the supplied wordmark as the real transparent navigation logo.
- [x] Remove the duplicate centered wordmark from behind the hero copy.
- [x] Fit product copy to the background with readable contrast.
- [x] Link primary actions to the live API/docs surfaces.
- [x] Serve and test the image asset through the running gateway.
- [x] Check browser console for errors.
- [x] Run the full regression suite and lint.

## Follow-up polish

P3: replace the derived transparent lockup with a source transparent logo if the
user supplies one, for perfect anti-aliasing at small sizes.

final result: passed
