# Assets — How Store Licenses Bind

[[[appendices.assets]]]

## Overview

[[[appendices.assets#overview]]]

Background for the license design in [[assets#licenses]]: when the terms of a store item bind the buyer, and so what a
record should keep. **None of it was checked against a store's current terms, and none of it is legal advice.** It is
what the design was reasoned from in the 2026-11-18 session, written down so a later change to the design can be
argued against it. A statement about one store is from memory until the terms page is read and the reading saved
([[assets#licenses]]).

## The grant is made when the item is acquired

[[[appendices.assets#acquisition]]]

An asset license is a contract formed when the account gets the item, whether by buying it or by claiming it free. It
is not made when the files are downloaded.

- **Terms are usually perpetual.** A marketplace license is typically written so that content already in a project
  keeps its license, because once the files are inside a shipped product nothing can switch them off.
- **New terms apply to new acquisitions** unless the agreement the buyer accepted let the store change it
  unilaterally. Many store agreements do contain such a clause, so *usually* is as strong as this can be put.
- **Creative Commons is irrevocable by its own text.** An author can stop offering an item; a copy already obtained
  keeps the license it came with.
- **A store that merges catalogs is the test case.** When Epic folded the Unreal Engine Marketplace and Sketchfab's
  store into Fab in 2024, items acquired earlier were recalled as keeping the license they were acquired under, with
  only new acquisitions on the Fab licenses. The `UE Marketplace` label on 11 of the 1,568 items of the owner's
  hand-made catalog is consistent with that and proves nothing about the terms.

## What the store can still gate

[[[appendices.assets#gate]]]

A game and an asset differ less in the license than in what stands between the buyer and the files each time they are
used.

- **A launcher or an account sits in the way of a game.** It can refuse to start or update the game until a new
  agreement is accepted, and a closed account takes the library with it. DRM or online activation does the same at a
  lower level. A DRM-free installer already downloaded has none of this: the publisher can change the text and has no
  way to apply it to the copy.
- **An asset in a project has nothing in the way.** Nothing checks in with the store, so changed terms have no
  practical way to reach it.
- **An asset not yet downloaded is the game's case.** It exists for the buyer only through the account and the
  store's launcher. A listing that is pulled, an account that is closed or a store that shuts can end the access while
  the right survives on paper. Only downloading the items that matter protects them.

## Downloading later, and the terms accepted on the way

[[[appendices.assets#download-later]]]

The license is fixed at acquisition; the gate to the files is the store as it is on the day of the download. Signing
in through the launcher may ask for the store's current terms. Whether accepting them changes the license of an item
already owned depends on the new text: terms that only cover use of the store and the account leave the item's license
alone, while terms that replace earlier licenses for the whole library put the buyer on the current one. Only the terms
settle which.

**The working assumption** the design takes is the safe one: for an item never downloaded, the store's *current* text
is the one the buyer is bound by, because it is the only one certain to have been accepted. An earlier text is better
for the buyer only if they can show they acquired under it and nothing since replaced it.

## What the record keeps because of this

[[[appendices.assets#record-keeps]]]

- **Two dates say which text is held and since when.** `acquired` is when the license was formed; `read` in the
  `.rehuterms` header is the day the saved text was read ([[assets#licenses]]). A scan reads the terms on the day it
  runs, so for an item acquired years earlier the two differ, and nothing recovers the older text unless it was saved.
- **A saved text is evidence, not a cache.** That is why a refresh never replaces it unasked: the text an item was
  acquired under may be the one that still applies, so it is not the tool's to overwrite.
- **The step before downloading is a refresh.** *Refresh License* ([[assets#licenses]]) shows whether the terms changed
  since the saved text, and the owner decides whether to replace it.

## What Fab's AI tags mean

[[[appendices.assets#ai-tags]]]

Fab's EULA (§16(l), read 2026-11-18 from `/i/eula/fab_eula`) has exactly two provisions on AI, and defines both
through tags on the listing. The library scan writes them as `advertised_tags`, prefixed as every tag it makes from a
store field is ([[assets#block]]).

- **NoAI**, written as `ai-forbidden` (the listing's `isAiForbidden`). Under a **Standard License**, NoAI content may not be used in datasets
  used by generative AI programs, in developing such programs, or as training input to them (also §6(vii)). Programs
  that only operate on the original content, classify it, or arrange existing content without making new content are
  outside that definition, so using AI tools on the file is not what the tag forbids.
- **What binds is the tag "at the time of your Transaction".** The scan reads today's listing, so a tag added or
  dropped since the item was got shows the listing's present state, not the terms it was got under.
- **On a Creative Commons item the CC license governs**; the clause is the Standard License's.
- **CreatedWithAI**, written as `ai-generated` (the listing's `isAiGenerated`). A disclosure, not a restriction: Fab requires sellers to tag
  content a material part of which was made with generative AI. Upscaling or content-aware fill does not count.
- **`isAiRestricted`** sits on the listing's seller (`user`), not on the item, and is not license data.
