# The public site

Everything served at <https://nglmrtn.com/Cerebro/> is static and lives on the `gh-pages` branch. This folder holds the sources that build it. The recorded data of the two frozen copies is not here; it lives only on `gh-pages`.

## Where things are

| URL | What it is | Built from |
|---|---|---|
| `/` | The landing: the winner poster, the system map and the five doors | `landing/` |
| `/dashboard/` | The Cerebro Dashboard, frozen at the end of the game, read-only | `frozen-dashboard/` |
| `/market/` | v07 Market, frozen after the game closed, read-only | `frozen-market/` |
| `/video/` | The three-minute video, full screen, nothing else | `video/index.html` |
| `/film/` | The old address of the video; it redirects to `/video/` | `film/index.html` |
| `/pitch/` | The pitch deck, slide by slide | the deck's own HTML, copied as it was presented |

## The landing

```
python3 site/landing/build.py            # writes site/landing/index.html
python3 site/landing/build.py out.html   # or anywhere else
```

`template.html` carries the head, the base styles and the poster. `build.py` adds the system map (the same diagram as the pitch deck, with a hover that names each part), the five doors and the entrance. The entrance is one table, `TIMELINE`, scaled to two seconds: the poster, then the Cerebro box alone at the centre of the map, then its lines out to each part. The cards are never transparent while they move.

## The frozen copies

Both copies work the same way. `capture.js` opens the real app on this machine and records every page and every read answer. `build.py` cleans what was recorded (keys, cookies, local paths, teammates' names, other teams' private messages) and writes a static site. `shim.tpl.js` is the small script that answers every read from the recorded files and refuses every write. `verify.js` opens the result in a clean browser and checks that every screen loads and nothing leaves the page.

```
cd site/frozen-dashboard          # or site/frozen-market
npm install playwright-core       # the scripts drive the Chrome already installed
node capture.js                   # needs the app running locally: dashboard API on :8791, market on :8793
python3 build.py                  # raw/ -> site/
node verify.js http://127.0.0.1:PORT   # after serving site/ with any static server
```

The game is over, so a new capture would only record the same closed state. The copies now on `gh-pages` were also touched up by hand after these scripts ran: the dashboard moved from the root to `/dashboard/`, both copies gained the shared Home · Dashboard · Market · Video · Pitch bar, and the market's shim learned to serve the card art. A rebuild from these scripts needs those three changes applied again.

## Publishing

`gh-pages` is a plain branch of static files; GitHub Pages serves it under the account's custom domain.

```
git worktree add ../pages gh-pages
cp site/landing/index.html ../pages/index.html     # or the folder that changed
cd ../pages && git add -A && git commit && git pull --rebase && git push
```

Never force-push it. Pages takes about a minute to serve a new commit, and browsers keep the old page for a few minutes more.
