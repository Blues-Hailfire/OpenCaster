# Environment: the enchanted jack-o'-lantern

[← OpenCaster](../README.md) · [Documentation](README.md)

**Environment** shows a jack-o'-lantern in a moonlit pumpkin patch, and
every spell cast from any wand acts on it (the wand, sound and lighting
effects play as usual).  The practice spell and cast labelling pause while
the page is open.

It's drawn the way the original app's art is: flat silhouettes in a single
colour, with the spell's effect as the one bright thing.  The whole night
takes the colour of the last spell (warm for fire, blue for water, green
for growing things, purple to start), and a lit pumpkin glows in its
candle's colour.

A fresh jack-o'-lantern has its candle lit.  Spells change it and play off
each other, the same way the clash elements do:

| Spells | On the jack-o'-lantern |
|--------|------------------------|
| Aguamenti · Glacius · Meteolojinx | douse the candle and fill it with water (it dribbles from the grin) · freeze the water (frost and icicles otherwise) · a rain or snow cloud that douses or fills it |
| Incendio · Verdimillious · Flagrate | light the candle (melts ice, boils water away, burns ropes, vines and flowers) · a green flame and a green-glowing face, or green sparks · a fiery sigil |
| Bombarda · Confringo · Expulso · Reducto · Finestra | smash it; **Reparo** mends it |
| Incarcerous · Brachiabindo · Fulgari | ropes, cords or glowing cuffs: it can't be moved |
| Petrificus Totalus · Immobulus · Impedimenta · Colloshoo · Stupefy | stone · frozen in place (the flame too) · everything slowed · glued to the ground · stunned, it keels over |
| Wingardium Leviosa · Ascendio · Accio | float it, and steer it with your wand · launch it · pull it towards you (or summon it back) |
| Flipendo · The Force Spell · Expelliarmus | knock it over, spilling what's inside · fling it away |
| Piertotum Locomotor · Arania Exumai · Ventus | it grows legs and hops · spiders scatter · a gust that blows the candle out and whirls leaves and petals |
| Protego · Salvio Hexia · Expecto Patronum | a shield, a ring of runes or a silvery guardian that blocks the next battle spell |
| Finite | ends every spell on it: shield, bindings, stone, charms, levitation, vanishing |
| Lumos · Nox | light up the patch · darken the night (the candle and glowing things still shine) |
| Colloportus · Alohomora, Aberto | seal the lid with a lock (smothers the candle) · unseal it |
| Orchideous · Herbivicus | a bouquet bursting out of the top · pumpkin vines that curl up it and bloom |
| Evanesco | vanish what's inside, or the jack-o'-lantern itself |
| Colovaria | change its colour (your house colour first) |
| Scourgify | scrub off soot, sigils and glue |
| Cantis · Quietus · Silencio | it sings · hums · goes quiet |
| Confundo · Rictusempra · Riddikulus · The Cheering Charm · The Sleeping Charm | dizzy · giggling · wobbly, in a party hat · golden cheer · asleep until the next spell |
| Appare Vestigium | reveals the last few spells cast here |

Its carved face changes with its mood: closed eyes asleep, crosses when
dizzy or stunned, a big grin when it's happy, an open mouth when it sings.

**Wingardium Leviosa** ties the floating pumpkin to the wand that cast it:
point the wand up, down, left or right and the pumpkin follows, leaning
into the pull (about 30° of turn takes it to the side of the scene).  When
the spell's own light ends, the wand glows gold instead of fading, the whole
time it holds the pumpkin.  Pressing all four pads to cast again ends the
charm: the glow goes, and the pumpkin drops straight down under gravity –
a bounce, a squash and a puff of dust – and stays where it lands (Accio
pulls it back to the middle).  The charm also ends if the pumpkin is
knocked down, bound or glued, when you leave the page, or on **Reset**.
Frozen by Immobulus, it hangs in mid-air until that wears off, then drops.
Cast Wingardium Leviosa again to pick it back up from where it lies.

**Reset the jack-o'-lantern** starts afresh.  The rules are plain Python in
`opencaster/environment.py`; `opencaster/gui/pumpkin.py` draws them, and
animates only while something moves (a lit candle flickers, so it keeps
moving while the page is open).
