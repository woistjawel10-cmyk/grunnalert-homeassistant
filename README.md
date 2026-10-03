<p align="center">
  <img src="logo.png" alt="GrunnAlert" width="128">
</p>

<h1 align="center">GrunnAlert voor Home Assistant</h1>

<p align="center">
  Live P2000-meldingen uit de provincie Groningen in je eigen Home Assistant.<br>
  Brandweer, ambulance en politie, binnen een seconde nadat de melding uitgaat.
</p>

<p align="center">
  <a href="https://grunnalert.nl"><b>grunnalert.nl</b></a> ·
  <a href="https://play.google.com/store/apps/details?id=com.starlightfm.p2000monitor"><b>GrunnAlert-app op Google Play</b></a>
</p>

---

## Wat is GrunnAlert?

GrunnAlert vangt zelf P2000-meldingen op met eigen ontvangers in Groningen en zet ze direct door naar de [GrunnAlert-app](https://play.google.com/store/apps/details?id=com.starlightfm.p2000monitor), de website [grunnalert.nl](https://grunnalert.nl) en nu ook naar Home Assistant.

Met deze integratie kun je:

- een melding op je telefoon krijgen als er iets in **jouw dorp of wijk** gebeurt
- een **lamp laten knipperen** of je speaker iets laten zeggen bij een melding in de buurt
- alle meldingen van het afgelopen uur **op de kaart** zien
- de laatste melding op je **dashboard** zetten

> **Ook onderweg op de hoogte blijven?**
> Download de gratis GrunnAlert-app voor Android:
> [Google Play](https://play.google.com/store/apps/details?id=com.starlightfm.p2000monitor)

## Installeren

### Via HACS (aanbevolen)

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=woistjawel10-cmyk&repository=grunnalert-homeassistant&category=integration)

1. Klik op de knop hierboven, of ga in HACS naar **Integraties > ⋮ > Aangepaste repositories** en voeg `https://github.com/woistjawel10-cmyk/grunnalert-homeassistant` toe als type **Integratie**.
2. Zoek **GrunnAlert** en klik op **Downloaden**.
3. Herstart Home Assistant.
4. Ga naar **Instellingen > Apparaten en diensten > Integratie toevoegen** en kies **GrunnAlert**.

[![Integratie toevoegen](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=grunnalert)

### Handmatig

Kopieer de map `custom_components/grunnalert` naar de map `custom_components` in je Home Assistant-configuratie en herstart.

## Instellen

Je kiest:

- **Gebied:** de hele provincie Groningen, of alleen de plaatsen die jij kiest
- **Diensten:** brandweer, ambulance, politie en/of overig

> Veel brandmeldingen staan bij GrunnAlert nog onder **Overig**. Wil je brandweermeldingen, laat Overig dan ook aan staan.

Later aanpassen kan via **Configureren** bij de integratie. Je kunt de integratie ook meerdere keren toevoegen, bijvoorbeeld een keer voor je eigen dorp en een keer voor de hele provincie.

## Wat krijg je?

| Entiteit | Wat het doet |
| --- | --- |
| `sensor.grunnalert_..._laatste_melding` | Tekst van de laatste melding. Plaats, straat, dienst, prio, eenheden, kaartlink en de 10 laatste meldingen staan in de attributen. |
| `sensor.grunnalert_..._tijd_laatste_melding` | Wanneer de laatste melding binnenkwam |
| `sensor.grunnalert_..._meldingen_afgelopen_uur` | Hoeveel meldingen er het afgelopen uur waren |
| `sensor.grunnalert_..._verbinding` | `live` (verbonden) of `polling` (vangnet) |
| `geo_location.*` | Recente meldingen met een bekende straat als punt op de kaart |

### Event voor automatiseringen

Bij elke nieuwe melding stuurt de integratie het event `grunnalert_alert` met onder andere:

```yaml
message: "P 1 BNN-01 Woningbrand Hoofdstraat Hoogezand"
discipline: fire            # fire, ambulance, police of other
discipline_label: Brandweer
priority: 1                 # 1, 2 of leeg
city: Hoogezand
street: Hoofdstraat
location: Hoofdstraat, Hoogezand
latitude: 53.16
longitude: 6.76
maps_url: https://www.google.com/maps?q=53.16,6.76
units: ["Hoogezand - TS-4231"]
received_at: "2026-10-03T00:12:34+00:00"
source: GrunnAlert
source_url: https://grunnalert.nl
```

## Blueprint: melding op je telefoon

[![Blueprint importeren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fwoistjawel10-cmyk%2Fgrunnalert-homeassistant%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fgrunnalert%2Fgrunnalert_melding.yaml)

Kies je telefoon, eventueel een paar plaatsen, en je krijgt een pushbericht bij elke melding. Tik op het bericht en je ziet direct waar het is.

## Voorbeelden

**Lamp rood laten knipperen bij een melding in je eigen dorp:**

```yaml
automation:
  - alias: GrunnAlert melding in het dorp
    triggers:
      - trigger: event
        event_type: grunnalert_alert
        event_data:
          city: Ten Boer
    actions:
      - action: light.turn_on
        target:
          entity_id: light.woonkamer
        data:
          color_name: red
          flash: short
```

**Melding uitspreken op een speaker:**

```yaml
automation:
  - alias: GrunnAlert uitspreken
    triggers:
      - trigger: event
        event_type: grunnalert_alert
    conditions:
      - "{{ trigger.event.data.priority == 1 }}"
    actions:
      - action: tts.speak
        target:
          entity_id: tts.google_translate_nl_nl
        data:
          media_player_entity_id: media_player.keuken
          message: >
            GrunnAlert: {{ trigger.event.data.discipline_label }} in
            {{ trigger.event.data.city }}.
```

## Hoe het werkt

- Meldingen komen **live** binnen via een WebSocket-verbinding met grunnalert.nl.
- Valt die verbinding even weg, dan haalt de integratie de laatste meldingen op als vangnet (standaard elke 2 minuten) en verbindt hij zelf opnieuw. Zolang live werkt, wordt er maar eens per half uur extra gecontroleerd.
- Na een herstart krijg je geen oude meldingen opnieuw als event.
- Komt dezelfde melding twee keer binnen (dat gebeurt bij P2000 soms), dan krijg je maar een event.
- Heb je de integratie vaker toegevoegd? Kies dan in de blueprint welke je wilt gebruiken, anders kun je sommige meldingen dubbel krijgen.
- Alleen meldingen uit de **provincie Groningen**.

## Privacy

- De integratie haalt altijd de meldingen van de hele provincie op en filtert **in je eigen Home Assistant** op jouw plaatsen. GrunnAlert weet dus niet welke plaatsen jij volgt.
- Bij het ophalen gaat een **anonieme installatie-ID** mee. Dat is een hash die niets over jou of je huis zegt. GrunnAlert gebruikt hem alleen om te tellen hoeveel Home Assistant-installaties er zijn.
- Zoals bij elke website ziet de server je IP-adres als je verbinding maakt. GrunnAlert slaat dat niet op bij je installatie-ID.
- Je thuislocatie blijft lokaal en wordt alleen gebruikt om de afstand tot een melding te berekenen.

Meer in de [privacyverklaring van GrunnAlert](https://grunnalert.nl/privacy/).

## Bronvermelding

Alle meldingen komen van **GrunnAlert** ([grunnalert.nl](https://grunnalert.nl)). Gebruik je de data ergens anders, bijvoorbeeld op een eigen dashboard of website, vermeld dan duidelijk GrunnAlert als bron.

P2000-meldingen zijn openbaar en bedoeld ter informatie. Bel bij nood altijd **112**.

---

<p align="center">
  Gemaakt door <b>StarlightFM</b> · <a href="https://grunnalert.nl">GrunnAlert</a>
</p>
