# 🌱 Veggohandla

**🇸🇪 Svenska** · 🇬🇧 [English](README.en.md)

Planera veckans veganska mat och få en färdig inköpslista med riktiga varor och
priser från Willys och Hemköp.

- **Veckan** – lägg recept på dagarna, ändra portioner, dra mellan dagar.
- **Recept** – skriv ingredienser som vanlig text (`500 g mjölig potatis`, `0,5 förp vegobullar`)
  eller importera från ICA, Köket, Arla m.fl. med en länk. Medan du skriver ser du vilken
  vara varje rad blir.
- **Handla** – listan räknas fram automatiskt. Varje ingrediens blir den billigaste veganska
  varan för just den mängd du behöver (750 g vegobullar → en 900 g-påse i stället för tre
  små). Kampanjer räknas med. Vill du ha ett visst märke trycker du *Byt* – valet sparas.
  Samma varor jämförs mellan Willys och Hemköp.
- **Sortiment** – ett lokalt index över kedjornas matvaror. Bara veganska varor visas:
  märkta veganska av kedjan, eller vars ingredienslista saknar animaliska ingredienser.

Allt körs lokalt på din dator. Inget konto, ingen molntjänst.

Gränssnittet finns på svenska och engelska. Knappen **SV / EN** uppe till höger byter språk,
och först används webbläsarens språk. Receptens, ingrediensernas och varornas namn är
alltid på svenska, eftersom butikerna är svenska.

## Kom igång

Kräver [uv](https://docs.astral.sh/uv/) (installerar rätt Python automatiskt).

```bash
git clone https://github.com/fsson/veggohandla.git && cd veggohandla
uv run manage.py serve
```

Öppna <http://127.0.0.1:8000>. Första gången skapas databasen i `data/` med 111
ingredienser och 5 veganska recept med bilder. Så länge `serve` körs hämtas sortimentet automatiskt
varje morgon (se nedan). Vill du köra appen hela tiden, utan att ha datorn igång, passar en
Raspberry Pi bra – se [Köra på en Raspberry Pi](#köra-på-en-raspberry-pi).

Receptbilderna laddas ner från [Wikimedia Commons](https://commons.wikimedia.org) när
databasen skapas. De har fria licenser, och fotograf och licens visas på varje receptsida.

### Hämta sortimentet

Willys och Hemköp ber i sin robots.txt om högst ett anrop per 10 sekunder och bara
mellan 04:00 och 08:45 UTC (05:00–09:45 svensk vintertid, 06:00–10:45 sommartid). Appen
följer det:

- `serve` uppdaterar sortimentet automatiskt varje morgon inom fönstret: priser och
  kampanjer (~20 minuter) och granskning av nya varor. Du kan också trycka *Uppdatera nu*
  under **Sortiment** eller köra `uv run manage.py index` inom fönstret.
- För att avgöra vad som är veganskt läser appen varje varas ingredienslista, en vara per
  anrop. Det är ~4 000 varor, men bara ~1 600 anrop ryms per morgon. Därför är sortimentet
  helt klart först efter **tre dagars körningar**. Det gäller bara första gången – därefter
  granskas bara nya varor, vilket tar några minuter.
- Du behöver inte vänta tre dagar: varor som dina recept använder granskas först, så
  inköpslistan fungerar redan efter första morgonen. Resten av sortimentet fylls på efter
  hand och syns i **Sortiment** när det är granskat.
- När tidsfönstret stänger pausas körningen. Inget går förlorat – nästa morgon fortsätter
  den där den slutade.
- Uppdateringen sker bara medan appen körs. Därför är en dator som alltid är på, som en
  Raspberry Pi, det smidigaste.

## Köra på en Raspberry Pi

En Raspberry Pi 4 (vilken minnesstorlek som helst) räcker gott. Appen körs då dygnet runt,
uppdaterar sortimentet varje morgon och nås från datorer och mobiler på ditt hemnätverk.

1. **Installera Raspberry Pi OS (64-bit).** Använd [Raspberry Pi Imager](https://www.raspberrypi.com/software/),
   välj *Raspberry Pi OS Lite (64-bit)*, och ställ i inställningarna in värdnamn
   (t.ex. `veggohandla`), användare, wifi och *Aktivera SSH*. 64-bitarsversionen krävs.
2. **Logga in och installera git:**

   ```bash
   ssh <användare>@veggohandla.local
   sudo apt update && sudo apt install -y git
   ```

3. **Hämta appen och installera den som tjänst:**

   ```bash
   git clone https://github.com/fsson/veggohandla.git && cd veggohandla
   ./deploy/install.sh
   ```

   Skriptet installerar uv, Python och beroenden, och sätter upp appen som en
   systemd-tjänst som startar automatiskt (och startar om sig själv om något går fel).
   Det tar några minuter första gången.
4. **Öppna** <http://veggohandla.local:8000> från en dator eller mobil på samma nätverk
   (eller `http://<pi:ns-ip-adress>:8000`).

Sedan sköter den sig själv: sortimentet uppdateras varje morgon, och appen startar igen
efter strömavbrott.

| Vad | Kommando |
|---|---|
| Uppdatera till senaste versionen | `cd ~/veggohandla && git pull && ./deploy/install.sh` |
| Se loggen | `journalctl -u veggohandla -f` |
| Starta om / stoppa | `sudo systemctl restart veggohandla` / `sudo systemctl stop veggohandla` |
| Annan port | `PORT=8080 ./deploy/install.sh` |
| Säkerhetskopiera | kopiera katalogen `~/veggohandla/data/` |

**Nå appen när du inte är hemma:** För att nå appen utifrån kan du sätta upp en egen VPN på Pi:n,
till exempel [PiVPN](https://pivpn.io) med WireGuard.

## Hur varorna väljs

Varje ingrediens har en regel för vilka varor som räknas som den, t.ex.
`krossade tomat -chili -vitlök` (alla ord ska finnas i varans namn, `-ord` utesluter).
Reglerna finns i `core/seed_data.py`. Bland de matchande varorna väljs den som blir
billigast för mängden, med hela förpackningar, lösvikt per kg och kampanjer som
"2 för 46 kr" (bara om du köper minst 2).

Nya ingredienser som du skriver i ett recept skapas automatiskt och matchar varor med
samma namn.

## Vegankontrollen

Kedjornas veganmärkning är ofullständig. Därför läses varje varas ingredienslista en gång:

- märkt vegansk → med
- ingredienslista utan animaliska ord (mjölk, ägg, vassle, honung, gelatin, karmin, D3 …) → med
- animaliskt ord hittat → aldrig med
- ingen ingredienslista → bara med om det är obearbetad frukt eller grönt

"Kan innehålla spår av mjölk" räknas inte, eftersom det gäller allergi och inte innehåll.
Under **Sortiment** står det för varje vara varför den räknas som vegansk.

## Data och säkerhetskopior

Allt (databas och bilder) ligger i `data/`. Kopiera katalogen för att ta en backup.
Katalogen ignoreras av git.

## Om butiksdatan

Willys och Hemköp (Axfood) har inget officiellt API. Appen använder samma öppna
JSON-anrop som deras webbplatser – bara när du indexerar, i den takt och under de tider
deras robots.txt anger, och resultatet sparas lokalt. Willys villkor tillåter användning av
innehållet *endast för personligt bruk*: kör appen själv, för dig själv. Det kan sluta fungera när som helst och kedjornas villkor gäller. Recept,
planering och inköpslista fungerar ändå, med de priser som senast hämtades.

## Utveckling

```bash
VEGGOHANDLA_DEBUG=1 uv run manage.py runserver   # utvecklingsserver med felsidor och omladdning
uv run pytest            # 140+ tester: enheter, sammanslagning, vegankontroll, varuval, vyer, översättning
```

Se [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (på engelska) för hur det hänger ihop.

### Översättningar

Svenska är källspråket: de svenska texterna i koden och mallarna är själva nycklarna, och
`locale/en/` innehåller den engelska översättningen. När du ändrar en text:

```bash
uv run manage.py makemessages -l en -i .venv -i data -i docs --no-obsolete --no-location
# översätt nya poster i locale/en/LC_MESSAGES/django.po; för ändrade texter, skriv om
# översättningen och ta bort både "#, fuzzy" och raden "#| msgid …" med den gamla texten
uv run manage.py compilemessages -l en     # skapar django.mo, som checkas in
```

Ett test (`core/tests/test_i18n.py`) misslyckas om en text saknar översättning, om
`django.mo` är gammal eller om svensk gränssnittstext läcker igenom på engelska sidor.
