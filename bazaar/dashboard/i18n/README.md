# Dashboard i18n (Spanish / English)

- Core: `../i18n.js` → `window.I18N` and the global shortcut `t(key, vars)`.
- One dictionary per scope in this folder: `I18N.register("es", {...}); I18N.register("en", {...});` with flat keys `scope.key`.
- Language: `I18N.lang` (`es` by default), stored in `localStorage["bazaar.lang"]`, forced with `?lang=en`. The ES | EN switch is at the bottom of the side menu. `I18N.setLang(lang)` saves and **reloads the page**, so text built when a screen file loads (module constants) is fine.
- Serving: the API serves only flat files under `static/`, so each dictionary has a symlink next to `index.html` (`i18n-<scope>.js -> i18n/<scope>.js`) and `index.html` loads `static/i18n-<scope>.js`. A new scope needs its symlink and its `<script>` line.

## API

| Call | Result |
|---|---|
| `t("home.title")` | string in the active language; falls back to Spanish, then to the key (with one console warning) |
| `t("home.rank", {n: 3})` | fills `{n}` |
| `I18N.plural(n, "common.tickN")` | uses `common.tickN.one` / `common.tickN.other`, fills `{n}` |
| `I18N.ordinal(3)` | `3.º` / `3rd` |
| `I18N.list(["A","B","C"])` | `A, B y C` / `A, B and C` |
| `I18N.n(1234.5, opts)` | `toLocaleString` with `es-ES` / `en-GB` |
| `I18N.locale` | `es-ES` / `en-GB` (for `toLocaleDateString` and friends) |
| `I18N.lang` | `es` / `en` |

Already language-aware in `window.ui` (use them, do not re-implement): `fmtNum`, `fmtP`, `fmtUsd`, `fmtAgo`, `typeChip` / `TYPE_LABEL`, `resultChip`, `sourceTag`, `teamTag`, `teamName`, `filterBar`, `priceBar`, `empty()`, `loading()`, `error()`, `confirm()` defaults, `toast`, `purposeLabel`, `keyHealth`, `venueRanking`, `negParts`.

Not translated: ids, card refs, card names, dealer names, venue names, `P`, and any text that comes from the server (brain text, dealer messages, news, logs).

## `common.*` keys (reuse these before adding your own)

Types: `common.buy` `common.sell` `common.swap` `common.bid` `common.duel` `common.dealer` `common.announcement`; plurals `common.buys` `common.sells` `common.swaps` `common.bids` `common.duels` `common.dealers` `common.announcements`.

Who decided: `common.source.opus|council|fallback|code`.

Results: `common.result.sent|vetoed|rejected|pending|notSent|closed|noDeal`.

People: `common.us` `common.usShort` `common.them` `common.rivals` `common.rivalsShort` `common.team` `common.teams` `common.team10us` `common.ally` `common.organisers` `common.all` `common.allF` `common.none` `common.noneF`.

Buttons: `common.accept` `common.cancel` `common.confirm` `common.close` `common.save` `common.send` `common.delete` `common.remove` `common.add` `common.edit` `common.copy` `common.copied` `common.open` `common.view` `common.viewAll` `common.viewMore` `common.viewLess` `common.refresh` `common.retry` `common.apply` `common.reset` `common.back` `common.turnOn` `common.turnOff` `common.approve` `common.reject` `common.search` `common.searchPlaceholder` `common.detail` `common.sure`.

States: `common.on` `common.off` `common.onF` `common.offF` `common.onCaps` `common.offCaps` `common.onFCaps` `common.offFCaps` `common.live` `common.history` `common.loading` `common.empty` `common.error` `common.noConnection` `common.notAvailable` `common.openState` `common.closedState` `common.paused` `common.active` `common.inactive` `common.pending` `common.done` `common.yes` `common.no` `common.ok` `common.new` `common.now` `common.today` `common.yesterday`.

Units and nouns: `common.tick` `common.ticks` `common.tickN` (plural) `common.agoTicks {n}` `common.inTicks {n}` `common.ago {x}` `common.in {x}` `common.points` `common.pts` `common.cash` `common.value` `common.price` `common.limit` `common.card` `common.cards` `common.set` `common.page` `common.pages` `common.album` `common.level` `common.round` `common.venue` `common.venues` `common.fee` `common.offer` `common.offers` `common.deal` `common.deals` `common.trades` `common.tradesShort` `common.volume` `common.gain` `common.loss` `common.total` `common.average` `common.time` `common.date` `common.type` `common.status` `common.result` `common.reason` `common.who` `common.with` `common.of` `common.and` `common.or` `common.from` `common.to` `common.for` `common.market` `common.brain` `common.council` `common.lab` `common.broker` `common.bot` `common.ladder` `common.marketTest` `common.collection` `common.spend` `common.budget` `common.key` `common.keys` `common.message` `common.messages` `common.thread` `common.threads`.

Rarities: `common.rarity.common|rare|epic|legendary`.

Game events: `common.event.bench|duels|duel_session|round|set_release|level|persona|venue|fee|day_opens|day_closes`.

API spend purposes: `common.purpose.strategy|council|duels|dealers|market|lab|smoke|brain_eval|external_intel|broker`.

Screen names (menu): `shell.nav.home|cerebro|noticias|coleccion|mercado|broker|duelos|competicion|rivales|supervision|laboratorio|bot`.

## Check

`python bazaar/dashboard/tools/i18n_check.py` lists keys used in the code but missing in a language, unused keys, and Spanish text still written in the `.js` files.
