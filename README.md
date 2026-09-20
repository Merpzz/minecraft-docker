# Custom Minecraft-server i Docker

En Minecraft-container där du väljer **Minecraft-version och modloader** med miljövariabler. Stöd för **vanilla, Fabric, Forge och NeoForge**. Servern installeras vid första start och ändras när du ändrar inställningarna. Moddar lägger du bara som `.jar`-filer i `mods/`.

## Snabbstart

```bash
cp .env.example .env
nano .env                    # sätt EULA=true, MC_VERSION, LOADER, MEMORY
docker compose up -d --build
docker compose logs -f       # första starten laddar ner och installerar servern
```

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
- **Port:** `HOST_PORT` byter porten utåt. Ändra inte `server-port` i `server.properties` (containern lyssnar på 25565 internt).
- **Rättigheter:** servern körs som `PUID:PGID` (standard 1000:1000), inte root. På Unraid: `PUID=99 PGID=100`.
- **Stopp:** `stop_grace_period: 2m` ger servern tid att spara världen. Använd `docker compose stop`/`down`.

## Kända begränsningar

- **NeoForge** finns från Minecraft 1.20.2. (1.20.1 använder Forge.)
- **Forge/NeoForge-installationen och riktig serverstart är ännu inte körd i en riktig container**, se nedan. Fabric och vanilla laddas ner med en enda jar och är enklast.
- Första starten kräver internet. Efter installationen startar servern utan att kontakta versions-API:erna.
- Väldigt gamla Forge-versioner (≤ 1.12.2) startas som `java -jar forge-*.jar`; de är byggda för Java 8 och fungerar som bäst på den.

## Tester

```bash
python3 -m unittest scripts/test_mcctl.py     # offline, nätverksanrop mockas
```

Verifierat live mot API:erna: versionsuppslag för Fabric, Forge och NeoForge (inkl. nya `26.x`-schemat och NeoForge-prefix), nedladdning och omväxling vanilla → Fabric, pinning av `latest`, moddvarningar. Verifierat med HTTP-anrop att installer-URL:erna svarar. **Ej verifierat:** Docker-bygget och att Forge/NeoForge-installerarna faktiskt körs, eftersom Docker och Java saknas i miljön där den här koden skrevs.
