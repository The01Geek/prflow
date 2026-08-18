<!-- prflow:implement-ref step=2.3.2 file=skills/implement/references/sweep-2-3-2-stranded-dependents.md start -->

#### 2.3.2 Stranded-dependents sweep (mandatory whenever the change deletes a method, file, route, or page)

2.3.1 prunes dead lines *inside* the functions you touched. This sweep handles the inverse blast radius — the things *outside* your diff that the deletion stranded. When a removal/cleanup PR deletes its primary target, it routinely leaves dangling artifacts the deletion stripped of purpose: now-callerless public methods, leftover asset files, dead arguments still being passed to a callee that stopped reading them, and — worst — *surviving* pages, links, menu entries, or route references that still point at the code you just deleted (a guaranteed 404 / fatal for users).

After deleting any public method, class, file, page, route, endpoint, asset, or template, before running tests, do this sweep:

1. Now-orphaned public surfaces. For every public method or function you removed the *callers* of (not the function itself), and for every file/asset the just-deleted code was the sole consumer of: grep the whole repo for remaining references. Zero references → it is part of *this* removal; delete it too. (E.g. a public method left as a zombie with zero callers after its only caller was removed; an image/template asset left after its sole consumer was deleted.)
2. Dead arguments to changed callees. For every callee whose signature or body you changed so it stops reading some inputs: re-check each call site and stop passing the now-ignored arguments/keys. (E.g. a caller still passing several now-dead keys into a helper after the receiver stopped reading them.)
3. **Surviving inbound links and route refs.** For every page, route, endpoint, or file path you deleted: grep the repo for that path/URL/route name (links in templates, menu/nav configs, `href`s, redirects, route tables, sitemap entries). Every surviving reference is a regression — remove the link, or restore the target if it was deleted in error. (E.g. a navigation page still linking to a sub-page after that sub-page's source file was deleted → users hit a 404.)
4. In-scope subtree completeness. If the issue scopes a directory/feature subtree for removal, walk the *whole* subtree — do not stop at the files the obvious entry points reference. An untraversed leaf page that still calls the deleted integration is in scope by definition. (E.g. an orphan leaf file left in place still calling the deleted integration, linked from a surviving index page, despite sitting inside the in-scope subtree.)

Treat any stranded dependent as a defect in **this** PR. A deletion PR is not done until grepping for the deleted symbols/paths returns nothing but the deletion itself.

**Scope boundary with Phase 4.1 (*Update Documentation*).** This sweep covers references in *code, config, and routing tables* — i.e. things that break behavior at runtime if left dangling. Prose references to the deleted symbols/paths inside `[[INTERNAL_DOC_LOCATION]]` (descriptions, walkthroughs, "to install X, do Y") are not in scope here; they are handled by the Phase 4.1 documentation pass (a subagent that invokes the `prflow:docs` skill). If your grep turns up only docs hits, note them and move on — do not edit `[[INTERNAL_DOC_LOCATION]]` from this phase.

<!-- prflow:implement-ref step=2.3.2 file=skills/implement/references/sweep-2-3-2-stranded-dependents.md end -->
