# Custom Minecraft-server i Docker

En Minecraft-container där du väljer **Minecraft-version och modloader** med miljövariabler. Stöd för **vanilla, Fabric, Forge och NeoForge**. Servern installeras vid första start och ändras när du ändrar inställningarna. Moddar lägger du bara som `.jar`-filer i `mods/`.

## Snabbstart

```bash
cp .env.example .env
nano .env                    # sätt EULA=true, MC_VERSION, LOADER, MEMORY
docker compose up -d
docker compose logs -f       # första starten laddar ner och installerar servern
```

Imagen byggs automatiskt av GitHub Actions vid varje push till `main` (och varje måndag för att få med säkerhetsuppdateringar i Java/Ubuntu) och hämtas från `ghcr.io/merpzz/minecraft-docker`. Du behöver alltså inte bygga på servern. Vill du ändå bygga lokalt:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

**Behörighet till imagen:** repot är privat, så imagen är det också. På servern: `echo <PAT> | docker login ghcr.io -u <användarnamn> --password-stdin`, där `<PAT>` är en GitHub-token (classic) med `read:packages`. Alternativt gör du paketet publikt: GitHub → Packages → `minecraft-docker` → Package settings → Change visibility. Då krävs ingen inloggning. Vill du låsa en version i stället för `latest`: sätt `IMAGE=ghcr.io/merpzz/minecraft-docker:sha-abc1234` i `.env`.

Serverkonsolen: `docker attach minecraft` (lämna med **Ctrl-P Ctrl-Q**, inte Ctrl-C, annars stoppas servern).

## Välj version

| Variabel | Värden |
|---|---|
| `MC_VERSION` | exakt version (`1.21.1`, `26.2`, …), `latest` eller `latest-snapshot` |
| `LOADER` | `vanilla`, `fabric`, `forge`, `neoforge` |
| `LOADER_VERSION` | tomt = Forge: *recommended*, övriga: senaste stabila. Kan också vara `latest` eller en exakt version (`21.1.172`) |

Vilka versioner som finns hämtas live från Mojang, Fabric, Forge och NeoForge. Med hjälpkommandot ser du vad som går att välja, utan att starta servern:

```bash
docker compose run --rm minecraft mcctl mc                        # alla Minecraft-versioner
docker compose run --rm minecraft mcctl loaders neoforge          # vilka MC-versioner NeoForge stödjer
docker compose run --rm minecraft mcctl loader neoforge 1.21.1    # NeoForge-versioner för 1.21.1
docker compose run --rm minecraft mcctl loader forge 1.20.1       # Forge-versioner (recommended/latest markeras)
docker compose run --rm minecraft mcctl resolve fabric 1.21.1     # vad som skulle installeras
```

Byter du `MC_VERSION`, `LOADER` eller `LOADER_VERSION` och kör `docker compose up -d` igen ersätts serverfilerna. **Värld, `mods/`, `config/` och `server.properties` rörs inte.**

### `latest` pinnas
`MC_VERSION=latest` (eller tom `LOADER_VERSION`) löses upp **en gång** och ligger sedan fast, så en omstart aldrig uppgraderar din värld till en ny Minecraft-version. Vill du uppgradera: sätt `UPDATE=true`, starta om, och sätt tillbaka till `false`. Gör alltid en backup av `data/world` före en versionsuppgradering, det går inte att gå tillbaka.

### Java
Fyra Java-versioner ligger i imagen och rätt väljs automatiskt utifrån vad Minecraft-versionen kräver (enligt Mojangs versionsdata): Java 8 för ≤ 1.16.5, 17 för 1.17–1.20.4, 21 för 1.20.5–1.21.x, 25 för 26.x.

## Unraid

Färdig mall: `unraid-template/minecraft-docker.xml` (förifyllda fält för version, loader, minne, operatörer, port, persistent lagring och sökvägar under `/mnt/user/appdata/minecraft/`, kör som 99:100).

- **Importera:** kopiera XML-filen till `/boot/config/plugins/dockerMan/templates-user/` på Unraid, eller lägg in mallens URL under Docker → Add Container → Template. Mallen väljs sedan i rullgardinen.
- **Port:** i Unraid är portmappningen och `SERVER_PORT` två fält. Värdsidan av mappningen kan vara vad som helst, men **containerporten i mappningen måste vara samma som `SERVER_PORT`**. Standard är 25565 för båda.
- `TemplateURL` och ikonen pekar på `raw.githubusercontent.com` och fungerar bara när repot är publikt. Importera annars filen manuellt enligt ovan (ikonen då utan bild).
- Mallen använder `--stop-timeout 120 --interactive --tty` (tid att spara världen, konsol via `docker attach`). Ej testad på en riktig Unraid.

## Serverport, operatörer och persistent lagring

**Port:** `SERVER_PORT=25565` (standard). Sätts både som port containern lyssnar på (`server-port` i `server.properties` skrivs om vid varje start) och som publicerad port. Ändra alltså porten i `.env`, inte i `server.properties`.

**Operatörer:** `OPS=Notch,jeb_` lägger spelarna i `ops.json` vid start, med nivå `OP_LEVEL` (1–4, standard 4). UUID slås upp hos Mojang. Två saker att veta:
- Det är **additivt**: spelare som du gjort op med `/op` i spelet ligger kvar, och att ta bort ett namn ur `OPS` gör ingen `/deop`. Redan tillagda spelare ändras inte (ändrad `OP_LEVEL` gäller bara nya).
- Om uppslaget misslyckas (fel namn, Mojang nere) varnar loggen och servern startar ändå. På server med `online-mode=false` beräknas UUID lokalt, utan uppslag.

**Persistent lagring:** allt i `data/` överlever redan `docker compose down`, men en separat mapp är till för det som ska överleva även om du raderar `data/` eller installerar om från början.
```bash
PERSIST=world,ops.json,whitelist.json,banned-players.json,server.properties
PERSIST_HOST_DIR=./persist          # valfri sökväg på värden, t.ex. /srv/minecraft-keep
```
Varje angiven sökväg (relativt serverfoldern) flyttas till `persist/` och ersätts av en symbollänk. Finns redan data där (t.ex. efter ominstallation) används den. Om både lokal och persistent kopia finns vinner den persistenta, och den lokala sparas som `<namn>.local-<tid>`, ingenting raderas. `world`, `ops.json`, `whitelist.json`, `banned-*.json` och `server.properties` skapas direkt på rätt plats; andra filer flyttas första gången de finns. Loggen varnar om `PERSIST` är satt men `/persist` inte är en monterad mapp (då försvinner datan med containern).

## Moddar och konfiguration

```
minecraft-docker/
├── mods/     ← släpp in .jar-filer här (Fabric/Forge/NeoForge-moddar)
├── config/   ← modarnas config-filer
└── data/     ← värld, server.properties, loggar, installerade serverfiler
```

1. Lägg moddarna i `mods/`.
2. `docker compose restart`.

Vid start kontrollerar containern varje jar i `mods/` och **varnar i loggen** om en mod verkar vara för fel loader (t.ex. en Fabric-mod på en NeoForge-server) eller inte är en giltig jar-fil. Den varnar bara, den tar aldrig bort något. Kom ihåg att moddar också är knutna till Minecraft-versionen, och att spelarna behöver samma moddar (klientsida) för det mesta.

## Övrigt

- **Minne:** `MEMORY=4G` (sätter -Xmx; `MEMORY_MIN` styr -Xms, annars samma). Extra JVM-flaggor: `JVM_OPTS`.
- **Rättigheter:** servern körs som `PUID:PGID` (standard 1000:1000), inte root. På Unraid: `PUID=99 PGID=100`.
- **Stopp:** `stop_grace_period: 2m` ger servern tid att spara världen. Använd `docker compose stop`/`down`.

## Kända begränsningar

- **NeoForge** finns från Minecraft 1.20.2. (1.20.1 använder Forge.)
- **Forge/NeoForge-installationen och riktig serverstart är ännu inte körd i en riktig container**, se nedan. Fabric och vanilla laddas ner med en enda jar och är enklast.
- Första starten kräver internet. Efter installationen startar servern utan att kontakta versions-API:erna.
- Väldigt gamla Forge-versioner (≤ 1.12.2) startas som `java -jar forge-*.jar`; de är byggda för Java 8 och fungerar som bäst på den.

## Tester

```bash
python3 -m unittest discover -s scripts       # offline, nätverksanrop mockas (körs också i GitHub Actions)
```

Verifierat live mot API:erna (och Mojangs namnuppslag för `OPS`): versionsuppslag för Fabric, Forge och NeoForge (inkl. nya `26.x`-schemat och NeoForge-prefix), nedladdning och omväxling vanilla → Fabric, pinning av `latest`, moddvarningar. Verifierat med HTTP-anrop att installer-URL:erna svarar. **Ej verifierat:** Docker-bygget (GitHub Actions-flödet är ännu inte körd), och att Forge/NeoForge-installerarna faktiskt körs, eftersom Docker och Java saknas i miljön där den här koden skrevs.
