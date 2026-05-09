"""Generate a debug.html surfacing the dev cruft and translated comments
that Falcom shipped inside Xanadu Next's data archives.

Reads from a previously-extracted output directory. Translations of the
Japanese commentary are hand-written; the page renders bilingual, with the
English line directly underneath each original Japanese line in accent color.
"""

from __future__ import annotations

import argparse
import html
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Per-line full translations. Keys are matched as substrings of a comment line
# (after the leading `//` and whitespace). Longer keys are tried first.
#
# Where a line has trailing tab-aligned commentary, the substring match is
# applied to the *whole* line so that fixed-width SFX-table rows (e.g.
# `SE_OK ,"XNSE000",0,0    // 決定`) work cleanly.

LINE_TRANSLATIONS: dict[str, str] = {
    # sound.tbl — header banter
    "効果音テーブル": "Sound effects table",
    "プログラマ以外はいじっちゃイヤ！": "Hands off if you're not a programmer!",
    # sound.tbl — section dividers
    "●システム　XNSE000～": "● SYSTEM (XNSE000~)",
    "●環境系　XNSE050～": "● AMBIENT (XNSE050~)",
    "●ギミック　XNSE100～": "● GIMMICKS (XNSE100~)",
    "●その他　XNSE200～": "● MISC (XNSE200~)",
    "●戦闘　XNSE300～": "● COMBAT (XNSE300~)",
    "●魔法　XNSE400～": "● MAGIC (XNSE400~)",
    "●ボイス　XNVO000～": "● VOICE (XNVO000~)",
    "●イベント　XNSE600～": "● EVENT (XNSE600~)",
    "●ガーディアン　XNSE700～": "● GUARDIAN (XNSE700~)",
    "●スキル　XNSE800～": "● SKILL (XNSE800~)",
    "●その他２　XNSE900～": "● MISC 2 (XNSE900~)",
    "ID        File  環位": "ID, file, env-position",
    # sound.tbl — system row descriptions
    "決定": "Confirm / OK",
    "キャンセル": "Cancel",
    "エラー音": "Error sound",
    "フォーカス音？（メニュースライド音）": "Focus sound? (menu slide sound)",
    "★地図の拡大、縮小": "★ Map zoom in/out",
    "武器、防具を装備する/はずす": "Equip / unequip weapon, armor",
    "★スキル、魔法をセットする/はずす": "★ Set / unset skill, magic",
    "★タブ切り替え": "★ Tab switch",
    "★ドラッグ": "★ Drag",
    "★ドロップ": "★ Drop",
    "★カーソル移動": "★ Cursor move",
    "★セーブオブジェに触れる": "★ Touch save object",
    "★セーブ": "★ Save",
    "売る/買う（清算終了）": "Sell / buy (transaction complete)",
    "通常アイテム入手": "Get a normal item",
    "イベントアイテムお宝ゲットー！": "Got an event treasure item!",
    "クラウンゲットー！": "Got a crown!",
    "レベルアップ": "Level up",
    "★レベルダウン": "★ Level down",
    "スキルアップ": "Skill up",
    "ガーディアンLVアップ①": "Guardian level-up (variant 1)",
    "ガーディアンLVアップ②": "Guardian level-up (variant 2)",
    "宿屋": "Inn",
    "★フキダシウインドウ出現": "★ Speech-bubble window appears",
    "★セリフ送り": "★ Advance dialogue",
    "★ガーディアン変更": "★ Switch guardian",
    "エリア切り替え": "Area transition",
    "アイテム拾う": "Pick up item",
    "★ゴールドを拾う": "★ Pick up gold",
    # sound.tbl — ambient
    "★そよ風（北の遺跡、魔粧の森全般）": "★ Light breeze (Northern Ruins, Forest of Mashou)",
    "★強風（イーグリット山外観）": "★ Strong wind (Mt. Eagrit exterior)",
    "★鳥（森系　お好みで）": "★ Birds (forest, use as you like)",
    "★虫（森系　お好みで）": "★ Insects (forest, use as you like)",
    "小川、水辺": "Stream, waterside",
    "★舟の上（湖）": "★ On a boat (lake)",
    "★水中": "★ Underwater",
    "滝": "Waterfall",
    "★溶岩（イーグリット山内部）": "★ Lava (Mt. Eagrit interior)",
    "街・夜": "Town, night",
    "波打ち際（街）": "Wave-edge / shoreline (town)",
    "★遠雷（ラスボスマップ）": "★ Distant thunder (final boss map)",
    "★波（遠い）": "★ Waves (distant)",
    # sound.tbl — gimmicks
    "木製扉（民家、地下遺跡など）": "Wooden door (houses, underground ruins, etc.)",
    "★街入り口扉": "★ Town entrance door",
    "★火山の扉": "★ Volcano door",
    "開錠": "Unlocking",
    "カギあかねー": "Key won't fit (\"can't open it!\")",
    "封印石板壊れる音 はめ込む音": "Sealing stone-tablet break — fitting in",
    "封印石板壊れる音 光があふれる音": "Sealing stone-tablet break — light overflows",
    "封印石板壊れる音 ヒビが入る音": "Sealing stone-tablet break — cracks form",
    "封印石板壊れる音 壊れる音": "Sealing stone-tablet break — shatter",
    "バリアドア（紫）出現": "Barrier door (purple) appears",
    "バリアドア（紫）消滅": "Barrier door (purple) disappears",
    "★ガントレットで岩破壊": "★ Smash a rock with the gauntlet",
    "タル破壊": "Smash a barrel",
    "ツボ割り音": "Pot-smash sound",
    "★飾台破壊": "★ Pedestal break",
    "★箱破壊": "★ Box break",
    "箱を押す時の「ズリッ…」って奴": "That \"zrtt…\" sound when you push a box",
    "★消滅（色箱？）": "★ Disappear (colored box?)",
    "★箱スイッチ（上に乗ると沈むやつ）": "★ Box switch (the kind that sinks when you stand on it)",
    "草を斬る音": "Slashing grass",
    "ストッパー解除": "Stopper released",
    "柵が開く音（O_0423）": "Fence-opening sound (O_0423)",
    "★モンスターから宝箱出現": "★ Treasure chest emerges from monster",
    "宝箱開け": "Open treasure chest",
    "宝箱閉め": "Close treasure chest",
    "ワープゲート起動 （ワープアイテム使用とは別の音です）": "Activate warp gate (different sound from using a warp item)",
    "ワープして消える": "Warp away (vanish)",
    "ワープして現れる": "Warp in (appear)",
    "★ブラックオニキス使用": "★ Use Black Onyx",
    "★レバー": "★ Lever",
    "★エレベーター起動/停止": "★ Elevator start / stop",
    "★エレベーター移動中": "★ Elevator in transit",
    "★火炎発射トラップ出る/引っ込む": "★ Flame-trap deploys / retracts",
    "★火炎発射": "★ Flame fires",
    "敵を殲滅したジングル": "Enemies-annihilated jingle",
    "★火山　落石": "★ Volcano: falling rock",
    "★火山　水蒸気が吹き出す": "★ Volcano: steam vents",
    "爆弾（箱や壷）": "Bomb (box or pot)",
    "★火炎放射（ループ）": "★ Flamethrower (loops)",
    "★地下遺跡　水門開閉": "★ Underground ruins: floodgate open/close",
    "★扉汎用（街外れの遺跡の扉、北の遺跡、湖底遺跡、奇岩城など）": "★ Generic door (ruins outside town, Northern Ruins, Lakebed Ruins, Strange-Rock Castle, etc.)",
    "★クラウンが宝箱から出現": "★ Crown emerges from chest",
    "★宝箱からガーディアンカード入手": "★ Get a guardian card from a chest",
    "★宝箱が出現する/消える（仕掛けを解いた時など）": "★ Treasure chest appears / vanishes (after solving a puzzle, etc.)",
    "★階段出現（地下遺跡）": "★ Staircase appears (Underground Ruins)",
    "★氷が解ける": "★ Ice melts",
    "★移動装置ビリビリ（異界・ループ）": "★ Mover-device buzz (Otherworld, looping)",
    "★階下への移動音（異界）": "★ Sound of moving down a floor (Otherworld)",
    "★扉がロック/解除される（異界）": "★ Door locks / unlocks (Otherworld)",
    "★ゆっくりと引っ込む柵や壁（奇岩城）": "★ Fence/wall slowly retracting (Strange-Rock Castle)",
    "★つり橋がかかる音": "★ Suspension bridge extends",
    "★巨大歯車が回りだす": "★ Giant cogwheel starts turning",
    "★水が流れる1": "★ Water flows 1",
    "★水が流れる2": "★ Water flows 2",
    "★水車が回る": "★ Waterwheel turns",
    "★橋が出てくる": "★ Bridge emerges",
    "★箱を落とす（木箱、色箱）": "★ Drop a box (wooden box, colored box)",
    "★箱を落とす2（重い箱）": "★ Drop a box 2 (heavy box)",
    # sound.tbl — player & combat
    "●プレイヤー　XNSE200～": "● PLAYER (XNSE200~)",
    "武器出し": "Draw weapon",
    "武器しまい": "Sheathe weapon",
    "★武器振り　素手": "★ Weapon swing — bare hands",
    "★武器振り　メイス": "★ Weapon swing — mace",
    "★武器振り　片手剣": "★ Weapon swing — one-handed sword",
    "★武器振り　両手剣": "★ Weapon swing — two-handed sword",
    "★武器振り　片手斧": "★ Weapon swing — one-handed axe",
    "★武器振り　両手斧": "★ Weapon swing — two-handed axe",
    "★武器振り　特殊系？": "★ Weapon swing — special?",
    "★ジャンプ": "★ Jump",
    "★着地": "★ Landing",
    "自分のダメージ": "Take damage",
    "自分の死亡": "Player death",
    "ガード（状態異常防御／魔法無効化専用）": "Guard (status-effect block / magic-nullify only)",
    "ガード（通常のいわゆるガード）": "Guard (regular block)",
    "カウンター": "Counter",
    "★溶岩に落ちる": "★ Fall into lava",
    "★復活（出現）": "★ Revive (appear)",
    "HP回復": "HP recover",
    "★SP回復": "★ SP recover",
    "★状態回復": "★ Status cure",
    "★蘇生（エリクサーで）": "★ Resurrect (via Elixir)",
    "★毒": "★ Poison",
    "★麻痺": "★ Paralysis",
    "★束縛": "★ Bind",
    "★盲目": "★ Blind",
    "★沈黙": "★ Silence",
    "★呪い": "★ Curse",
    "クリティカルヒット": "Critical hit",
    "状態異常　凍結": "Status: freeze",
    "状態異常　凍結解除": "Status: freeze cleared",
    # sound.tbl — footsteps
    "●足音系　XNSE250～": "● FOOTSTEPS (XNSE250~)",
    "足音（カーペット1）": "Footsteps (carpet 1)",
    "足音（地面1）": "Footsteps (ground 1)",
    "足音（草1）": "Footsteps (grass 1)",
    "足音（鉄板1）": "Footsteps (iron plate 1)",
    "足音（砂1）": "Footsteps (sand 1)",
    "足音（浅瀬1）": "Footsteps (shallows 1)",
    "足音（石1）": "Footsteps (stone 1)",
    "足音（木1）": "Footsteps (wood 1)",
    "★足音（雪1）": "★ Footsteps (snow 1)",
    "空中": "Mid-air",
    "★城カーペット": "★ Castle carpet",
    "石リバーブ": "Stone reverb",
    "★土リバーブ": "★ Dirt reverb",
    "★鉄リバーブ": "★ Iron reverb",
    "★水リバーブ": "★ Water reverb",
    "水に入る音": "Entering water",
    "★水から出る音": "★ Exiting water",
    "★砂リバーブ": "★ Sand reverb",
    # sound.tbl — magic
    "●スキル・魔法　XNSE300～": "● SKILL / MAGIC (XNSE300~)",
    "30:マジックランス発射": "30: Magic Lance fires",
    "30:マジックランス着弾": "30: Magic Lance impact",
    "31:タイタンブロー落下": "31: Titan Blow descends",
    "31:タイタンブロー着弾": "31: Titan Blow impact",
    "32:デス溜め": "32: Death (charge-up)",
    "32:デス発射": "32: Death fires",
    "32:デス着弾": "32: Death impact",
    "33:ファイア(仕様せず下記※参照)": "33: Fire (unused — see ※ below)",
    "34:ファイアウォール円周上に炎が走る": "34: Fire Wall — flames trace the circle",
    "34:ファイアウォール炎上": "34: Fire Wall — burst",
    "35:イグニシオン発動": "35: Ignition triggers",
    "36:フリージング発射（フロストベル発射兼用）":
        "36: Freezing fires (also used for Frost Bell launch)",
    "36:フリージング着弾.": "36: Freezing impact.",
    "37:_フロストベル着弾": "37: Frost Bell impact",
    "37:フロストベル氷割れ": "37: Frost Bell — ice shatter",
    "38:アヴァランチ発動": "38: Avalanche triggers",
    "39:ブリッツアロー発動": "39: Blitz Arrow triggers",
    "40:ライトニング発動": "40: Lightning triggers",
    "41:トールハンマー発動": "41: Thor's Hammer triggers",
    "※ファイアの効果音は以下のものを当ててください":
        "※ Use the following SFX for Fire:",
    "ファイア：溜め": "Fire: charge-up",
    "ファイア：炎発射": "Fire: flame launch",
    "音が必要": "needs SFX",
    # sound.tbl — skills
    "00:thrust (突き": "00: thrust (突き = stab)",
    "01:bush (吹き飛ばし": "01: bush [knock-back] (吹き飛ばし)",
    "02:sweep attack (なぎ払い": "02: sweep attack (なぎ払い)",
    "03:cyclon (回転攻撃　溜め": "03: cyclone (spinning attack — charge)",
    "03:cyclon (回転攻撃　斬り": "03: cyclone (spinning attack — slash)",
    "04:buttleccry (戦歌": "04: battlecry (戦歌)",
    "05:charge (突進": "05: charge (突進)",
    "06:power thrust (強突き": "06: power thrust (強突き)",
    "07:force_blast (剣気": "07: force blast (剣気 = sword aura)",
    "08:______(殲滅の剣風 溜め ※エフェクト未完の溜保留":
        "08: ______ (Annihilation Blade — charge ※ effect unfinished, charge on hold)",
    "08:______(殲滅の剣風 発射 ※エフェクト未完の溜保留":
        "08: ______ (Annihilation Blade — launch ※ effect unfinished, charge on hold)",
    "08:______(殲滅の剣風 着弾 ※エフェクト未完の溜保留":
        "08: ______ (Annihilation Blade — impact ※ effect unfinished, charge on hold)",
    "どっちでもいいかな": "either is fine, I guess",
    "09:火炎の剣": "09: Sword of Flame",
    "10:冷気の剣": "10: Sword of Frost",
    "11:電撃の剣": "11: Sword of Lightning",
    "特に音は必要なさそう": "no SFX really needed",
    "12:集中": "12: Focus",
    "13:豪腕": "13: Mighty Arm",
    "14:覚醒智": "14: Awakened Wisdom",
    "15:強健": "15: Robust",
    "16:寂静": "16: Stillness",
    "17:機敏": "17: Agile",
    "18:根こそぎ": "18: Uprooting",
    "19:不意打ち": "19: Surprise Attack",
    "20:迎撃": "20: Intercept",
    "21:熟達の楯": "21: Mastery of the Shield",
    "22:片手装備": "22: One-handed Equipment",
    "23:根性": "23: Guts",
    "24:凶暴化": "24: Frenzy",
    "25:守りの構え": "25: Defensive Stance",
    "26:血の憤激": "26: Bloody Rage",
    "27:韋駄天": "27: Idaten (god of speed)",
    "28:高速攻撃": "28: High-speed Attack",
    "29:看破": "29: See Through",
    "●ザコモンスター　XNSE400～": "● ENEMY MONSTER (XNSE400~)",
    "XNSE400～　共通系": "XNSE400~ common types",
    "紫壁トラップなどで敵が出現する": "enemy appears via purple-wall trap, etc.",
    # bgm.tbl — header
    "★ＢＧＭテーブル★": "★ BGM TABLE ★",
    "ファイル名 / 開始 / ループ(開始) / ループ(終了) / ループする曲？(0 or 1)":
        "filename / start / loop (start) / loop (end) / looping song? (0 or 1)",
    "※曲の並び順さえズレなければ自由に書き換えて頂いて構いません。＞サウンドさん":
        "※ Feel free to edit, as long as the song order doesn't shift. → Sound team",
    # bgm.tbl — track captions
    "オープニング	（ムービー）": "Opening (movie)",
    "エンディング	（不死鳥ムービー）": "Ending (Phoenix movie)",
    "スタッフロール	（歌）": "Staff roll (song)",
    "タイトル画面": "Title screen",
    "街": "Town",
    "チュートリアル	（地下神殿）": "Tutorial (Underground Temple)",
    "廃墟			（北の遺跡）": "Ruins (Northern Ruins)",
    "地下遺跡		（地下遺跡、ダークネスロード、）": "Underground ruins (Underground Ruins, Darkness Road)",
    "火山			（イーグリット山）": "Volcano (Mt. Eagrit)",
    "迷いの森		（魔粧の森）": "Forest of Wandering (Forest of Mashou)",
    "湖底の遺跡		（湖底の遺跡　でも狭くてザコも出ないらしい）":
        "Lakebed Ruins (Lakebed Ruins — but apparently it's so narrow no mooks even spawn there)",
    "封異門			（ザナドゥ・ラビリンス）": "Sealed-anomaly Gate (Xanadu Labyrinth)",
    "異界			（時の狭間）": "Otherworld (Crevice of Time)",
    "ガルシス城		（奇岩城）": "Galsis Castle (Strange-Rock Castle)",
    "小ボス			（マップの要所要所に出てくるデカザコ）":
        "Mini-boss (the big mook that shows up at key map points)",
    "中ボス			（トレント戦、カニグモ戦、インフェルノ戦、湖底遺跡のボス戦、ローレライ戦）":
        "Mid-boss (Treant fight, Crab-spider fight, Inferno fight, Lakebed Ruins boss, Lorelei fight)",
    "ラスボス1		（ガルシス第一形態）": "Final boss 1 (Galsis, first form)",
    "ラスボス2		（ガルシス第二形態）": "Final boss 2 (Galsis, second form)",
    "イベント汎用	（ザナのテーマ　軽め）": "Generic event (Xana's theme, mellow version)",
    "姫の真意		（ラスボス後イベント）": "The princess's true intent (post-final-boss event)",
    "ラスボス前		（ラスボス前イベント）": "Pre-final-boss (pre-final-boss event)",
    "挿入ムービー1	（湖排水）": "Inserted movie 1 (Lake drainage)",
    "異界関係イベント": "Otherworld-related event",
    "クレジット後モノローグ": "Post-credits monologue",
    # bgm.tbl — comma-separated annotation rows
    "オープニング(ムービー)": "Opening (movie)",
    "エンディング（不死鳥ムービー）": "Ending (Phoenix movie)",
    "スタッフロール（歌）": "Staff roll (song)",
    # effect.tbl — header
    "エフェクトテーブル": "Effects table",
    "アルファベットは大文字で": "Alphabet uppercase",
    "ラベル名に Tab は禁止！": "No tabs in label names!",
    "エフェクトファイルナンバー割り当て表": "Effect-file-number assignment table",
    "エリアエフェクト": "Area effect",
    "XX:エリアナンバー YY:エフェクトナンバー": "XX: area number, YY: effect number",
    "スキルエフェクト": "Skill effect",
    "シナリオエフェクト": "Scenario effect",
    "システムエフェクト": "System effect",
    "敵固有エフェクト": "Enemy-specific effect",
    "プレイヤーエフェクト": "Player effect",
    "黒魔法エフェクト": "Black-magic effect",
    "白魔法エフェクト": "White-magic effect",
    "３０００番台": "(3000 range)",
    "４０００番台": "(4000 range)",
    "５０００番台": "(5000 range)",
    "６０００番台": "(6000 range)",
    "７０００番台": "(7000 range)",
    "８０００番台": "(8000 range)",
    "９０００番台": "(9000 range)",
    "！！！！！！！！！！新規作成時にはファイル番号に注意！！！！！！！！！！！！！！！":
        "!!!!! BE CAREFUL OF THE FILE NUMBER WHEN ADDING NEW ENTRIES !!!!!",
    "店頭売り魔法": "Magic sold in shops",
    "初期": "Initial",
    "トレント後": "After Treant",
    "カニグモ後": "After Crab-Spider",
    "インフェルノ後": "After Inferno",
    "デス後": "After Death",
    "マジックランス": "Magic Lance",
    "ファイアウォール": "Fire Wall",
    "フロストベル": "Frost Bell",
    "フリージング": "Freezing",
    "ブリッツアロー": "Blitz Arrow",
    "ライトニング": "Lightning",
    "イグニシオン": "Ignition",
    "アヴァランチ": "Avalanche",
    "トールハンマー": "Thor's Hammer",
    "ファイア": "Fire",
    "ニードル": "Needle",
    "ロック": "Rock",
    "デス": "Death",
    "ブレイズ": "Blaze",
    "アイス": "Ice",
    "フロスト": "Frost",
    # efc_mdl.tbl
    "エフェクト用モデル定義テーブル": "Effect-use model definition table",
    "現在の上限＝31番まで。": "Current limit = up to #31.",
    "矢": "Arrow",
    "カニグモ落盤（大）": "Crab-Spider rockfall (large)",
    "カニグモ落盤（中）": "Crab-Spider rockfall (medium)",
    "カニグモ落盤（小）": "Crab-Spider rockfall (small)",
    "カニグモミサイル（子ガニ）": "Crab-Spider missile (baby crab)",
    "ほおずき爆弾（トレント）": "Lantern-fruit bomb (Treant)",
    "エフェクト用氷結": "Effect-use freeze",
    "岩": "Boulder",
    "9961用光": "Light for 9961",
    "城バリア（核）": "Castle barrier (core)",
    "異界ゲート（光の輪）": "Otherworld gate (ring of light)",
    "異界ゲート（ゲート）": "Otherworld gate (the gate itself)",
    "異界ゲート（光注（赤））": "Otherworld gate (light pillar — red)",
    "異界ゲート（光注（青））": "Otherworld gate (light pillar — blue)",
    "異界ゲート（光注（黄））": "Otherworld gate (light pillar — yellow)",
    "ビホルダーのトゲ": "Beholder spikes",
    "４つのクラウン": "The four crowns",
    "魔法デス（パーツ①）": "Magic Death (part 1)",
    "魔法デス（パーツ②）": "Magic Death (part 2)",
    "我岩": "Self-rock(?)",
    "リッチ分身": "Lich double",
    "スケルトン鎖": "Skeleton chain",
    "テオパルト": "Teopalt",
    "ガルシスマップ地面エフェクト１": "Galsis-map ground effect 1",
    "ガルシスマップ地面エフェクト２": "Galsis-map ground effect 2",
    "ガルシスマップ地面エフェクト３": "Galsis-map ground effect 3",
    # speed.tbl
    "プレイヤーの歩行速度定義ファイル": "Player walk-speed definition file",
    # piece09.tbl
    "ランダムマップパーツ定義ファイル": "Random-map piece definition file",
    "ゲート情報": "Gate info",
    # ── .scp map-script commentary ──────────────────────────────────────
    # Section dividers / standard headers
    "マップ初期化": "Map init",
    "マップ初期化時にボスパーツを全部読み込む": "Load all boss parts on map init",
    "戦闘前イベント続き": "Pre-battle event (continued)",
    "初期状態": "Initial state",
    "ＮＰＣテスト用（井上）": "NPC test (Inoue)",
    "寺院（初期化）": "Temple (init)",
    "寺院（イベント用）": "Temple (event use)",
    "ギルド（初期化）": "Guild (init)",
    "マップ  酒場１Ｆ": "Map: Tavern 1F",
    "マップ  宿酒場２Ｆ　宿泊用部屋（シャルのいない部屋）デバッグ用":
        "Map: Inn-Tavern 2F lodging room (the room without Shal) — DEBUG USE",
    "ドラゴンスレイヤー": "Dragonslayer",
    # Common code-block context comments
    "DEBUG版exe判定": "DEBUG-build EXE check",
    "デバッグキャラ。": "debug character.",
    "シャル会話": "Shal conversation",
    "アニエス": "Agnes",
    "アニエス霊薬繰り返し": "Agnes (repeating elixir)",
    "シネスコ時スペクタクルズON": "Spectacles ON during cinemascope",
    "未完成マップへの扉へカギ": "Key for the door to the unfinished map",
    "ワイバーン": "Wyvern",
    "ハーピー": "Harpy",
    "奇岩城、塔の頂上。ラスボスマップ　第一形態用":
        "Strange-Rock Castle, top of the tower. Final boss map (first form).",
    "SE再生": "Play SE",
    "MP_0655のフェードアウトを解除": "Cancel MP_0655's fade-out",
    "コア": "Core",
    "ＤＳ": "DS (Dragonslayer)",
    "ヒットマップ": "Hit-map",
    "注視ターゲット設定": "Set gaze target",
    "オートターゲットモードON": "Auto-target mode ON",
    "空中戦": "Aerial combat",
    "空中戦（旧）": "Aerial combat (old)",
    "地上戦（旧）": "Ground combat (old)",
    "ビットは地上戦まで隠す": "Hide bits until ground combat",
    "ビット隠す（呼び出しはプログラム側でやる）":
        "Hide bits (calls happen on the program side)",
    "胴体": "Body",
    "ＨＰリンク設定": "HP-link setup",
    "リーゼ戦用カメラOFF": "Camera off for Liese fight",
    "リーゼ攻撃モード": "Liese attack mode",
    "リーゼ戦用カメラ": "Camera for Liese fight",
    "リーゼロット": "Lieselotte",
    "ガルシス": "Galsis",
    "リーゼ": "Liese",
    "主人公": "the protagonist",
    "PCの動きを止める": "Stop PC movement",
    "PCの処理": "PC handling",
    "移動禁止": "Movement forbidden",
    "スキル禁止": "Skills forbidden",
    "キャンプ禁止": "Camp forbidden",
    "移動、スキル、キャンプ禁止": "Movement, skills, camp all forbidden",
    "NPC処理": "NPC handling",
    "ボス戦闘後イベントを呼び出し用(DEBUG)":
        "Used for invoking post-boss event (DEBUG)",
    "ＥＶ ボス戦闘前イベント": "EV: pre-boss-battle event",
    "EV ボス戦闘前イベント": "EV: pre-boss-battle event",
    "EV リーゼ攻撃モード": "EV: Liese attack mode",
    # Storyboard comments in MP_0685 / MP_0686
    "▼奇岩城・塔屋上": "▼ Strange-Rock Castle — tower rooftop",
    "塔の螺旋階段を登り、屋上へ上がるとイベント開始。":
        "After climbing the tower's spiral staircase to the roof, the event begins.",
    "ガルシスの姿はどこにもなく、リーゼロットのみが待っている。":
        "Galsis is nowhere to be seen; only Lieselotte is waiting.",
    "周囲を訝しげに見回す主人公。": "The protagonist looks around suspiciously.",
    "ここでリーゼロットが後ろへ振り向く。":
        "Here, Lieselotte turns to look behind her.",
    "主人公に背中を向けた状態。": "Her back is turned to the protagonist.",
    "リーゼロット、主人公のほうへ振り返る。":
        "Lieselotte turns to face the protagonist.",
    "リーゼロット、祈りのモーション。":
        "Lieselotte performs the praying motion.",
    # Dated dev change-log lines (★YY/MM/DD: …)
    "★05/05/18:ブラックオニキス禁止フラグON":
        "★ 2005/05/18: Black Onyx prohibition flag ON",
    "★05/06/21:イベントアイテム箱→開けっぱで残す。":
        "★ 2005/06/21: event-item chests → leave them in the open state.",
    "★05/06/22:水没してた宝箱（ラングストーン）が浮上してくる演出を追加":
        "★ 2005/06/22: added effect — the submerged chest (Langstone) floats up.",
    "★05/06/20:Ｆクリスタルは最初の一回だけでいい事になりました（ひ）":
        "★ 2005/06/20: F-Crystal — turns out we only need it the first time. — signed (ひ / 'Hi')",
    "★05/05/19追記：ドヴォルザークと現在戦闘中ならイベントトリガー無視":
        "★ 2005/05/19 addendum: if currently fighting Dvorak, ignore event triggers",
    "★05/05/19追記：「戦闘直前までスキップ」に変更":
        "★ 2005/05/19 addendum: changed to 'skip until just before the battle'",
    "★05/05/19追記分（ココマデ） ==============================================":
        "★ 2005/05/19 addendum block (ENDS HERE) ====================================",
    "★05/09/28:効果説明修正":
        "★ 2005/09/28: effect-description fix",
    # Inline workaround banter
    "カメラがじゃむるバグがあるのでここでやっちまう。":
        "There's a bug where the camera jams, so we just deal with it here.",
    "この時プレイヤーがあらぬ方向を向いてることがありますが、それはデバッグで飛んだ時です。":
        "The player will sometimes face a weird direction here — but that only happens when you've debug-warped to this map.",
    # Debug-menu (Debug-Chan / Momo) labels
    "シナリオジャンプ": "Scenario Jump",
    "Ａパート（到着～冒険開始まで）": "A Part (Arrival → adventure start)",
    "Ｂパート（インフェルノまで）": "B Part (up to Inferno)",
    "Ｃパート（フローレにＤＳもらうまで）":
        "C Part (until you get the DS from Fleurette)",
    "Ｄパート（終了まで）": "D Part (to the end)",
    "フラグ制御": "Flag switches",
    "ボス戦": "Boss fights",
    "やめる": "Stop",
    # path-component nouns
    "退避": "BACKUP (lit. 'evacuated')",
    "素顔": "bare-face / true-face",
    "素顔Ver": "bare-face version",
    "アイコン元": "icon master/source",
    "三角机": "triangular desk",
    "コピー": "Copy of … (Japanese-Windows duplicate)",
    "コピー ～ TITLE": "Copy of TITLE",
    "コピー ～ AREA07_97": "Copy of AREA07_97",
}


@dataclass(frozen=True, slots=True)
class DevArtifact:
    path: Path
    kind: str


# ---------------------------------------------------------------------------
# Discovery


def find_dev_artifacts(root: Path) -> list[DevArtifact]:
    out: list[DevArtifact] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        s = rel.as_posix()
        low = s.lower()
        kind: str | None = None
        if "コピー" in s:
            kind = "windows-copy"
        elif "退避" in s:
            kind = "backup"
        elif "素顔" in s:
            kind = "bareface"
        elif "/old/" in low or "(old)" in low:
            kind = "old"
        elif "/bak/" in low or low.endswith("_backup.scp"):
            kind = "backup"
        elif "test" in low and (
            low.endswith(".png") or low.endswith(".scp") or "test/" in low
        ):
            kind = "test"
        elif "_sample" in low:
            kind = "sample"
        elif s.rsplit("/", 1)[-1].lower() in {
            "aura_test.png",
            "spot_old.png",
            "uv_test.png",
            "blank.png",
            "cursor1.png",
            "cursor2.png",
        }:
            name = s.rsplit("/", 1)[-1].lower()
            kind = (
                "test" if "test" in name else "old" if "old" in name else "placeholder"
            )
        if kind:
            out.append(DevArtifact(path=rel, kind=kind))
    return out


def read_tbl(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("cp932", "shift_jis", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def has_japanese(s: str) -> bool:
    return any("　" <= c <= "鿿" or "＀" <= c <= "￯" for c in s)


def translate_line(line: str) -> str | None:
    """Return an English version of `line`, or None if no Japanese was matched.

    The strategy is two-pass:
      1. If any LINE_TRANSLATIONS key matches the *whole-line* substring, we
         build a translated copy of the line by replacing every matched key
         with its English (longest first).
      2. Anything still in Japanese after substitution stays in Japanese; the
         caller can decide whether to render it.
    """
    if not has_japanese(line):
        return None
    out = line
    matched = False
    for k in sorted(LINE_TRANSLATIONS, key=len, reverse=True):
        if k in out:
            out = out.replace(k, LINE_TRANSLATIONS[k])
            matched = True
    if not matched:
        return None
    return out


# ---------------------------------------------------------------------------
# Rendering

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Xanadu Next — debug / dev cruft</title>
<style>
  :root {{
    --bg: #0f1014;
    --panel: #181a21;
    --border: #262a35;
    --fg: #e7e7ea;
    --muted: #8a8e9c;
    --accent: #c7a86b;
    --accent-soft: #f6e5b8;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--fg);
                font: 13px/1.5 ui-sans-serif, system-ui, sans-serif; }}
  header {{ padding: 16px 22px; background: var(--panel);
            border-bottom: 1px solid var(--border); }}
  header h1 {{ margin: 0 0 4px; font-size: 18px; font-weight: 600; }}
  header p {{ margin: 0; color: var(--muted); font-size: 12px; max-width: 80ch; }}
  header a {{ color: var(--accent); }}
  main {{ padding: 22px; max-width: 1100px; }}
  h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.06em;
        color: var(--accent); margin: 28px 0 8px; font-weight: 600; }}
  h2 .count {{ color: var(--muted); font-weight: 400; }}
  .lede {{ color: var(--muted); margin: 0 0 12px; max-width: 80ch; }}
  .panel {{ background: var(--panel); border: 1px solid var(--border);
            border-radius: 4px; padding: 14px 16px; margin-bottom: 14px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  td, th {{ padding: 4px 8px; vertical-align: top; border-bottom: 1px solid var(--border);
            text-align: left; font-size: 12px; }}
  th {{ color: var(--muted); font-weight: 500; }}

  /* Bilingual blocks */
  .bilingual {{ font: 12.5px/1.55 ui-monospace, monospace;
                background: #0c0d10; border: 1px solid var(--border);
                border-radius: 4px; padding: 10px 14px; overflow-x: auto; }}
  .bilingual .ja  {{ color: var(--fg); white-space: pre; }}
  .bilingual .en  {{ color: var(--accent-soft); white-space: pre;
                     border-left: 2px solid var(--accent); padding-left: 6px;
                     margin-left: -8px; }}
  .bilingual .pair {{ margin-bottom: 4px; }}
  .bilingual .raw {{ color: var(--muted); white-space: pre; }}

  .tag {{ display: inline-block; padding: 1px 7px; border-radius: 3px;
          background: #2a3242; color: var(--fg); font-size: 11px;
          margin-right: 4px; }}
  .tag.test {{ background: #4a3023; color: #f3c0a4; }}
  .tag.old {{ background: #2c2c44; color: #b8b8ff; }}
  .tag.backup {{ background: #3a2c44; color: #d4b0e8; }}
  .tag.bareface {{ background: #44382c; color: #e8c7a0; }}
  .tag.windows-copy {{ background: #3a4434; color: #b6e8a0; }}
  .tag.placeholder {{ background: #2a2a2a; color: #c0c0c0; }}
  .tag.sample {{ background: #2c4044; color: #a0d4e8; }}
  code {{ background: #0c0d10; padding: 1px 6px; border-radius: 3px;
          font: 12px ui-monospace, monospace; color: var(--fg); }}
  ul {{ margin: 4px 0 12px 20px; padding: 0; }}
  ul li {{ margin-bottom: 2px; font-size: 12px; }}
</style>
</head>
<body>
<header>
  <h1>Xanadu Next — dev cruft &amp; translated comments</h1>
  <p>Things Falcom forgot to clean up before pressing the disc, plus the
     bilingual rendering of every Japanese commentary line in the data
     tables. Each Japanese line shows the original on top, with the English
     directly underneath in gold. ← <a href="index.html">back to viewer</a></p>
</header>
<main>
{body}
</main>
</body>
</html>
"""


def render_artifact_table(items: list[DevArtifact]) -> str:
    rows = []
    for a in items:
        href = html.escape(a.path.as_posix())
        rows.append(
            '<tr>'
            f'<td><span class="tag {a.kind}">{a.kind}</span></td>'
            f'<td><a href="{href}" target="_blank">{html.escape(a.path.as_posix())}</a></td>'
            '</tr>'
        )
    return f"<table><tbody>{''.join(rows)}</tbody></table>"


def render_bilingual(text: str) -> str:
    """Render a tbl text as bilingual JP/EN, with non-comment lines passed through."""
    out: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            out.append('<div class="pair raw"> </div>')
            continue
        en = translate_line(line) if has_japanese(line) else None
        if en:
            out.append(
                '<div class="pair">'
                f'<div class="ja">{html.escape(line)}</div>'
                f'<div class="en">↪ {html.escape(en)}</div>'
                '</div>'
            )
        else:
            out.append(f'<div class="pair raw">{html.escape(line) or "&nbsp;"}</div>')
    return f'<div class="bilingual">{"".join(out)}</div>'


def section_dev_cruft(items: list[DevArtifact]) -> str:
    by_kind: dict[str, list[DevArtifact]] = defaultdict(list)
    for a in items:
        by_kind[a.kind].append(a)

    descriptions = {
        "windows-copy": (
            "Files whose names start with the Japanese-Windows prefix "
            "<b>コピー ～</b> (<i>kopī ~</i>) — what Explorer auto-names a "
            "duplicated file when you Ctrl+C/Ctrl+V it. Someone right-clicked, "
            "copied, and shipped the dupe."
        ),
        "backup": (
            "Date-stamped backup folders. Falcom's modeling team used "
            "<b>退避</b> (<i>taihi</i>, lit. 'evacuated') for "
            "'set this aside before I edit it'. Dates encode YYMMDD — "
            "<code>041126</code> = 2004-11-26, <code>050129</code> = "
            "2005-01-29 (months before the original July 2005 release)."
        ),
        "bareface": (
            "<b>素顔Ver</b> = 'bare-face version'. An alternate version of "
            "the protagonist's helmet model with the helmet off / face "
            "visible. Shipped alongside the helmeted version actually used "
            "in-game."
        ),
        "old": (
            "Folders explicitly named <code>old</code> or <code>(OLD)</code> "
            "containing previous revisions of models, motions, or maps that "
            "were superseded but never removed."
        ),
        "test": (
            "Test files (UV-mapping check sheets, dummy textures, "
            "<code>AURA_TEST.G32</code> at 1024×1024, etc.) left in the "
            "data directories."
        ),
        "sample": "Files marked <code>_sample</code>.",
        "placeholder": (
            "Tiny placeholders. <code>BLANK</code>, <code>cursor1</code>, "
            "<code>cursor2</code> all decode to the same fully-white 16×16 "
            "from a single 18-byte source — three filenames pointing at one "
            "identical image."
        ),
    }

    blocks = []
    for kind, group in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        blocks.append(
            f'<h2>{kind} <span class="count">({len(group)})</span></h2>'
            f'<p class="lede">{descriptions.get(kind, "")}</p>'
            f'<div class="panel">{render_artifact_table(group)}</div>'
        )
    return "".join(blocks)


def section_master_art(root: Path) -> str:
    candidates = [
        ("DATA/SYSTEM/system/アイコン元.png",
         "Master icon sheet (591 KB) — every UI icon gets cropped from this. "
         "<b>アイコン元</b> = 'icon master/source'."),
        ("DATA/picture/picture/STAFF.png",
         "Staff/credits roll. 512 × 5120 — a single tall image scrolled by "
         "<code>G32_LoadStaffImage</code> at 0x004e1c00 in XANADU.exe."),
        ("DATA/SYSTEM/system/AURA_TEST.PNG",
         "1024 × 1024 noise-pattern test texture for the aura/glow shader."),
        ("DATA/SYSTEM/system/SPOT_OLD.PNG",
         "Earlier spotlight cookie (kept after the new one shipped)."),
        ("DATA/picture/picture/コピー ～ TITLE.png",
         "Title-screen art with the Japanese-Windows 'Copy of' prefix — "
         "<b>コピー ～ TITLE</b> = 'Copy of TITLE'."),
    ]
    cards = []
    for relpath, note in candidates:
        target = root / relpath
        if not target.exists():
            target = next((p for p in root.rglob(Path(relpath).name) if p.is_file()),
                          None)
        if target is None:
            continue
        rel = target.relative_to(root).as_posix()
        href = html.escape(rel)
        cards.append(
            '<div class="panel" style="display:flex;gap:14px;align-items:center;">'
            f'<a href="{href}" target="_blank"><img src="{href}" alt="" '
            'style="max-width:140px;max-height:140px;'
            'background:repeating-conic-gradient(#1d1f27 0 25%,#14161c 0 50%) 50%/12px 12px;'
            'image-rendering:pixelated;"></a>'
            f'<div><div><code>{href}</code></div>'
            f'<p class="lede" style="margin-top:6px">{note}</p></div></div>'
        )
    return '<h2>Master / source art</h2>' + "".join(cards)


def section_summary_stats(items: list[DevArtifact]) -> str:
    by_kind: dict[str, int] = defaultdict(int)
    for a in items:
        by_kind[a.kind] += 1
    chips = " ".join(
        f'<span class="tag {k}">{k}</span> <b>{v}</b>'
        for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])
    )
    return (
        '<h2>Summary</h2>'
        f'<div class="panel">{chips}<br>'
        f'Total flagged dev artifacts: <b>{len(items)}</b></div>'
    )


def section_tbl_bilingual(root: Path) -> str:
    targets = [
        ("DATA/WAVE/sound.tbl",
         "Sound effects table",
         "Includes the 'do not touch if you're not a programmer' warning, "
         "section dividers, and per-cue commentary describing every "
         "<code>SE_*</code> sound."),
        ("DATA/BGM/bgm.tbl",
         "BGM table — full track commentary",
         "Every track has a parenthetical note describing where it plays "
         "— including the dev's aside about the Lakebed Ruins track ('but "
         "apparently it's so narrow no mooks even spawn there') and the "
         "polite request to the sound team."),
        ("DATA/EFFECT/effect/effect.tbl",
         "Effects table — header rules",
         "Pipeline rules from the effects lead."),
        ("DATA/EFFECT/effect/efc_mdl.tbl",
         "Effect-model definitions",
         "Capped at <code>#31</code>; per-slot inline comments name each "
         "model."),
        ("DATA/chr/player/speed.tbl",
         "Player walk-speed table",
         ""),
        ("DATA/Map/area09/piece09.tbl",
         "Random-map piece definitions (area09)",
         "Area09 is the only area that uses procedural map assembly. "
         "This table defines gates and reusable map pieces."),
    ]
    blocks: list[str] = []
    for rel, title, intro in targets:
        full = root / rel
        if not full.exists():
            continue
        text = read_tbl(full)
        # Extract only comment lines + any line containing Japanese plus a
        # surrounding context for short tables. For sound.tbl & bgm.tbl we
        # want the full content; for piece09 we limit.
        if "piece09" in rel:
            text = "\n".join(text.splitlines()[:60])
        elif "effect.tbl" in rel:
            # Just the header block (first comment block + a few entries)
            lines = text.splitlines()
            cut = next(
                (i for i, ln in enumerate(lines)
                 if i > 4 and ln and not ln.lstrip().startswith("//")),
                40,
            )
            text = "\n".join(lines[: cut + 8])
        elif "efc_mdl" in rel:
            text = "\n".join(text.splitlines()[:50])
        intro_html = f'<p class="lede">{intro}</p>' if intro else ""
        blocks.append(
            f'<h2>{html.escape(title)}</h2>'
            f'<p class="lede"><code>{html.escape(rel)}</code></p>'
            f'{intro_html}'
            f'{render_bilingual(text)}'
        )
    return "".join(blocks)


def section_scp(root: Path) -> str:
    """All 577 .scp files are plaintext map scripts. Surface the highlights
    plus an index of every file's first comment line, both bilingual."""
    scps = sorted(root.rglob("*.scp"))
    if not scps:
        return ""

    # Curated highlights — full bilingual rendering for the most colorful
    # files. Each entry: (relpath, title, intro, slice).
    highlights = [
        (
            "DATA/Map/area00/MP_009e.scp",
            "Debug-Chan",
            "<code>MP_009e.scp</code> defines an NPC named "
            "<b>Debug-Chan</b> (internal name <code>Momo</code>) tucked away "
            "in a copy of the inn-tavern's 2F lodging room. Talking to her "
            "opens a debug menu that warps you anywhere in the scenario, "
            "flips flags, fights bosses, opens hidden maps, and grants "
            "special items. The dev gated her behind a "
            "<code>check_game_flag(4090)</code> 'DEBUG-build EXE check'.",
            (1, 80),
        ),
        (
            "DATA/Map/area00/MP_0042.scp",
            "NPC test (\"by Inoue\")",
            "<code>MP_0042.scp</code> credits a developer named Inoue "
            "(<b>井上</b>) for an NPC test scene. The NPCs themselves break "
            "the fourth wall: <i>'Since he's got a red shirt on, &quot;Red "
            "Shirt&quot; is what to call the boy'</i> and <i>'I'm "
            "Momo-chaaaan! I was originally gonna be the heroooine! Sooo not "
            "fair!'</i>",
            (1, 50),
        ),
        (
            "DATA/Map/area06/MP_0685.scp",
            "Final-boss map storyboard",
            "<code>MP_0685.scp</code> is the final boss map. Its top "
            "comment block is a literal <b>storyboard</b> — the dev wrote "
            "the cinematic blocking line by line in Japanese inside the "
            "script: protagonist climbs the spiral staircase, Galsis is "
            "nowhere, only Lieselotte is waiting, etc. Plus dated change-log "
            "entries with the ★ marker.",
            (1, 100),
        ),
        (
            "DATA/Map/area06/MP_0639.scp",
            "Key for an unfinished map",
            "<code>MP_0639.scp</code> contains the line <b>'未完成マップ"
            "への扉へカギ'</b> = <i>'key for the door to the unfinished "
            "map'</i> — a door whose room was never built but the lock is "
            "still wired up.",
            (1, 30),
        ),
    ]

    cards: list[str] = []
    for rel, title, intro, (start, end) in highlights:
        full = root / rel
        if not full.exists():
            continue
        text = read_tbl(full)
        excerpt = "\n".join(text.splitlines()[start - 1 : end])
        cards.append(
            f'<h3 style="margin:18px 0 6px;font-size:13px">{html.escape(title)}</h3>'
            f'<p class="lede">{intro}</p>'
            f'{render_bilingual(excerpt)}'
        )

    # Dated changelog table — all ★YY/MM/DD lines across all scp files.
    changelog_pat = re.compile(r"★\s*0[5-7]/\d{2}/\d{2}")
    changelog: list[tuple[str, str, str]] = []
    for p in scps:
        try:
            text = p.read_bytes().decode("cp932")
        except UnicodeDecodeError:
            continue
        rel = p.relative_to(root).as_posix()
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("//"):
                continue
            if not changelog_pat.search(stripped):
                continue
            en = translate_line(stripped) or ""
            changelog.append((rel, stripped, en))
    # Dedup by (line, translation) since many files copy the same change-note.
    seen: set[tuple[str, str]] = set()
    unique_changelog: list[tuple[str, str, str]] = []
    for rel, line, en in changelog:
        key = (line, en)
        if key in seen:
            continue
        seen.add(key)
        unique_changelog.append((rel, line, en))
    rows = []
    for rel, line, en in unique_changelog:
        rows.append(
            "<tr>"
            f'<td><code style="font-size:11px">{html.escape(rel)}</code></td>'
            f'<td style="white-space:pre-wrap">{html.escape(line)}</td>'
            f'<td style="white-space:pre-wrap;color:var(--accent-soft)">{html.escape(en)}</td>'
            "</tr>"
        )
    changelog_html = (
        "<table>"
        "<thead><tr><th>first occurrence</th><th>JP</th><th>EN</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )

    # Headers index — first JP comment line in each file.
    headers: list[tuple[str, str, str]] = []
    for p in scps:
        try:
            text = p.read_bytes().decode("cp932")
        except UnicodeDecodeError:
            continue
        rel = p.relative_to(root).as_posix()
        first_ja = ""
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("//") and has_japanese(s):
                if not s.replace("/", "").strip(" -=*"):
                    continue
                first_ja = s
                break
        if not first_ja:
            continue
        en = translate_line(first_ja) or ""
        headers.append((rel, first_ja, en))
    header_rows = []
    for rel, ja, en in headers:
        header_rows.append(
            "<tr>"
            f'<td><a href="{html.escape(rel)}" target="_blank">'
            f'<code style="font-size:11px">{html.escape(rel)}</code></a></td>'
            f'<td>{html.escape(ja)}</td>'
            f'<td style="color:var(--accent-soft)">{html.escape(en)}</td>'
            "</tr>"
        )
    headers_html = (
        f'<details><summary>Show all {len(headers)} script headers</summary>'
        '<table style="margin-top:8px">'
        "<thead><tr><th>file</th><th>JP first comment</th><th>EN</th></tr></thead>"
        f"<tbody>{''.join(header_rows)}</tbody></table></details>"
    )

    intro = (
        f"<p class=\"lede\">All <b>{len(scps)}</b> "
        '<code>.scp</code> files are <b>plaintext Shift-JIS map scripts</b> '
        "in Falcom's custom DSL (<code>DEF</code> / <code>RES</code> / "
        "<code>SE</code> / <code>BGM</code> / etc.). Total ≈ "
        f"{sum(p.stat().st_size for p in scps) // 1024} KB. Below: curated "
        "highlights with bilingual rendering, every dated dev change-log "
        "line found across the corpus, and an index of every script's first "
        "comment header.</p>"
    )

    return (
        '<h2>Map scripts (.scp) — dev commentary</h2>'
        f'{intro}'
        f'{"".join(cards)}'
        '<h3 style="margin:24px 0 6px;font-size:13px">Dated dev change-log lines</h3>'
        '<p class="lede">Lines starting with ★YY/MM/DD found in <code>.scp</code> '
        'files (deduped by content). Most edits cluster around 2005-05-18 '
        '(black-onyx restriction in boss maps), 2005-06-21 (event-item chest '
        'state policy), and 2005-09-28 (a late polish pass).</p>'
        f'<div class="panel">{changelog_html}</div>'
        '<h3 style="margin:24px 0 6px;font-size:13px">All script headers</h3>'
        f'<div class="panel">{headers_html}</div>'
    )


def section_guardian_iterations(root: Path) -> str:
    full = root / "DATA/equip/equip/guardian.tbl"
    if not full.exists():
        return ""
    text = read_tbl(full)
    lines = text.splitlines()
    excerpt: list[str] = []
    in_excerpt = False
    chunk_count = 0
    for ln in lines:
        if ln.startswith("// 0") and chunk_count >= 4:
            break
        if ln.startswith("//==="):
            in_excerpt = True
        if in_excerpt:
            excerpt.append(ln.rstrip())
            if ln.startswith("// 0"):
                chunk_count += 1
    body = html.escape("\n".join(excerpt))
    return (
        '<h2>Guardian spirits — balance iterations</h2>'
        '<p class="lede"><code>DATA/equip/equip/guardian.tbl</code> '
        '(marked <code>05/07/19Ver</code>) ships with previous balance '
        'curves left in as <code>//</code>-commented lines next to the new '
        'ones. You can see the Damonkatze level table being retuned from '
        '<code>1, 51, 130, 240, 380</code> down to '
        '<code>1, 31, 70, 120, 180, 250…</code>.</p>'
        f'<pre style="font:12px ui-monospace,monospace;background:#0c0d10;'
        'border:1px solid var(--border);border-radius:4px;padding:12px;'
        f'white-space:pre-wrap;color:var(--fg)">{body}</pre>'
    )


def build_html(root: Path) -> str:
    items = find_dev_artifacts(root)
    body = "".join(
        [
            section_summary_stats(items),
            section_master_art(root),
            section_scp(root),
            section_tbl_bilingual(root),
            section_dev_cruft(items),
            section_guardian_iterations(root),
        ]
    )
    return PAGE.format(body=body)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="xanadu-debug")
    p.add_argument(
        "out",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "out",
    )
    args = p.parse_args(argv)
    if not args.out.is_dir():
        p.error(f"not a directory: {args.out}")
    page = build_html(args.out)
    target = args.out / "debug.html"
    target.write_text(page, encoding="utf-8")
    print(f"wrote {target} ({len(page) // 1024} KB)")
    print(f"open: file://{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
