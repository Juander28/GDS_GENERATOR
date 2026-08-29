"""Resistencias de poly, plegadas en serpentin y colocadas en su propia banda.

Por que no van como los condensadores. Un MIM vive en metal4/metal5 y se monta
ENCIMA del array ya ruteado sin gastar area, porque esas capas estan virgenes
(ver caps.py). Una resistencia de poly esta al nivel de las puertas: ocupa
suelo. Asi que no puede ser un paso puramente aditivo sobre capas libres, tiene
que tener sitio reservado.

Lo que si se copia de los condensadores es el resto de la idea: se coloca
DESPUES de rutear, y sus dos terminales bajan al trunk de su net por metal3,
que el array deja libre. Eso rompe la misma circularidad -- la resistencia
querria saber donde cayeron los trunks y los trunks no dependen de ella.

**El PCell del PDK hace casi todo el trabajo.** `gf180.ppolyf_u_high_Rs_res`
dibuja el cuerpo de poly, el implante pplus, el bloqueo de silicida, el
marcador RES_MK que exige PRES.9a y los contactos de los dos extremos. No hay
que dibujar nada de eso a mano. Lo que si hay que poner es el metal1 encima de
los contactos y las tiras que unen un segmento con el siguiente.

**Por que plegar.** El area de una resistencia va con el CUADRADO de su ancho,
porque para una R dada el largo va con el ancho: area = R*W^2/hoja. Conviene
por tanto el ancho minimo que permita el DRC, que segun PRES.1 es 0.8 um. Pero
entonces 1.2 Mohm son 302 um de largo, que de una tirada no cabe en ninguna
celda: hay que plegarlo en N segmentos en serie.

**El paso entre segmentos no es PRES.2.** PRES.2 pide 0.4 um entre cuerpos
resistivos, pero el PCell es mas alto que su cuerpo -- 1.6 um para un cuerpo de
0.8 -- porque el bloqueo de silicida y el implante sobresalen. El paso lo manda
la altura de la celda, no la regla.
"""

from __future__ import annotations

import os
import warnings

warnings.filterwarnings("ignore")

import gdsfactory as gf

from coil_layout.pdk_manager import get_pdk_module
from coil_layout.placement import GRID, snap

#: Ancho minimo del cuerpo resistivo. OJO: la regla NO es PRES.1 (0.8 um), que
#: es la de la resistencia de poly normal. La de alta hoja -- ppolyf_u_1k/2k/3k,
#: que es la que da los 3.17 kohm por cuadro -- tiene su propio juego de reglas
#: HRES.*, y HRES.2 pide 1 um. Con 0.8 salen 22 violaciones, una por segmento.
ANCHO_MIN = 1.0
#: Hueco vertical entre segmentos, MEDIDO SOBRE LA CAPA `resistor`, que es la
#: que mira HRES.1 (0.4 um de separacion minima). Esa capa no cubre solo el
#: cuerpo: se extiende 0.4 um por arriba y por abajo, asi que para un cuerpo de
#: 1 um mide 1.8. Con 0.2 de hueco el paso salia 2.0, la separacion 0.2 y
#: saltaban 21 violaciones, una por pliegue. 0.45 deja 0.45 de margen.
HUECO = 0.45
#: Ancho de las tiras de metal1 que unen segmentos. Va IGUAL que el pad a
#: proposito: con 0.30 dentro de un pad de 0.40 queda un escalon de 0.05 a cada
#: lado, y `space` con metrica euclidiana cuenta esa muesca como separacion --
#: 87 violaciones de M1.2a que no eran dos formas cerca, sino una sola forma
#: con un entrante.
STRAP = 0.40
#: Cuanto sobresale el metal1 del contacto por cada lado. CO.6b se queja si es
#: menor de 0.04, y M1.3 pide 0.1444 um2 de area, asi que 0.09 va sobrado.
ENC = 0.09
#: (sin usar desde que se cubre cada cabeza entera) Lado del cuadrado de metal1. Lo manda M1.3, que pide
#: 0.1444 um2 de area minima: 0.38 al cuadrado CLAVADO. Con 0.28 saltaban dos
#: violaciones de area y ademas CO.6b, que se queja si el metal solapa el
#: contacto menos de 0.04 por un lado. Con 0.40 sobra por los dos motivos.
PAD = 0.40


def _modelo_pdk(model: str) -> str:
    """Del modelo SPICE al res_type del PCell de gdsfactory."""
    m = model.lower()
    if "3k" in m:
        return "3k"
    if "2k" in m:
        return "2k"
    return "1k"


def dimensiona(r_um: float, ancho_um: float, hoja_ohm_sq: float,
               alto_max_um: float) -> tuple[int, float]:
    """Cuantos segmentos y de que largo, para una R dada y un alto maximo.

    Devuelve (n_segmentos, largo_de_cada_uno). Se pliega lo justo para caber
    en `alto_max_um`, porque cada pliegue anade dos cabezas de contacto y
    ensancha la banda.
    """
    cuadros = r_um and (r_um / hoja_ohm_sq)
    largo_total = cuadros * ancho_um
    alto_celda = ancho_um + 0.8 + HUECO          # cuerpo + faldas del PCell
    ancho_um = max(ancho_um, ANCHO_MIN)
    n = max(1, int(alto_max_um // alto_celda))
    return n, largo_total / n


def serpentin(model: str, ancho_um: float, largo_total_um: float,
              n: int, nombre: str = "res"):
    """Componente con `n` segmentos en serie, unidos por metal1.

    Los segmentos se apilan en vertical y se unen en zigzag: el extremo derecho
    del primero con el derecho del segundo, el izquierdo del segundo con el
    izquierdo del tercero, y asi. Sale un serpentin de verdad y no una escalera,
    que es lo que ahorra las tiras largas de metal.
    """
    gf180 = get_pdk_module("gf180")
    L = gf180.layer
    c = gf.Component()
    largo = largo_total_um / n
    paso = ancho_um + 0.8 + HUECO

    import klayout.db as kdb
    ancho_um = snap2(max(ancho_um, ANCHO_MIN))
    largo = snap2(largo)
    seg = gf180.ppolyf_u_high_Rs_res(l_res=largo, w_res=ancho_um, volt="5V")

    #  Los contactos se leen de la geometria del PCell en vez de estimarlos con
    #  offsets a ojo, y hay que cubrirlos TODOS con metal o `CO.6` se queja de
    #  los que queden desnudos.
    #
    #  Pero NO todos son lo mismo, y confundirlos costo un cortocircuito que solo
    #  vio el LVS. El PCell de `ppolyf_u_high_Rs_res` pone seis contactos por
    #  segmento: dos sobre el poly de cada extremo (las dos cabezas de la
    #  resistencia) y **dos mas sobre una isla de difusion**, a la izquierda del
    #  todo, que es la TOMA DE SUSTRATO del dispositivo -- el tercer terminal del
    #  modelo de tres nodos. Medido en el PCell con `l_res=76.45`:
    #
    #      comp      x -1.76 .. -1.34            <- la isla de sustrato
    #      contacto  x -1.66 .. -1.44   comp     <- toma de sustrato
    #      contacto  x -0.57 .. -0.35   poly     <- cabeza izquierda
    #      contacto  x 76.80 .. 77.02   poly     <- cabeza derecha
    #
    #  Metiendolos en la misma envolvente, el metal1 de la cabeza izquierda tapa
    #  tambien la toma y ata el extremo de la resistencia al sustrato. En el
    #  layout extraido salian los CINCO tramos con un extremo en `VSS`
    #  (`R$56 VSS $I332 VSS ... ppolyf_u_3k`) y la realimentacion, en vez de ir
    #  de `G_OUT_P` a `OUT`, iba a masa. El DRC daba 0: dos metales que se tocan
    #  no violan ningun espaciado.
    #
    #  Asi que se separan: las cabezas cubren solo los contactos sobre POLY, y la
    #  toma de sustrato lleva su propio pad, aparte. Entre los dos quedan 0.87 um
    #  menos los dos encierros, de sobra para `M1.2a` (0.23).
    li = next(i for i in seg.kcl.layout.layer_indexes()
              if seg.kcl.layout.get_info(i).name == "contact")
    lc = next(i for i in seg.kcl.layout.layer_indexes()
              if seg.kcl.layout.get_info(i).name == "comp")
    reg = kdb.Region(seg.kdb_cell.begin_shapes_rec(li)); reg.merge()
    difusion = kdb.Region(seg.kdb_cell.begin_shapes_rec(lc)); difusion.merge()
    de_poly, de_sustrato = [], []
    for pol in reg.each_merged():
        caja = pol.bbox().to_dtype(seg.kcl.layout.dbu)
        (de_sustrato if not (kdb.Region(pol) & difusion).is_empty()
         else de_poly).append(caja)
    contactos = de_poly
    medio = seg.dxmin + seg.dxsize / 2
    izq = [b for b in contactos if b.center().x < medio]
    der = [b for b in contactos if b.center().x >= medio]

    def envolvente(grupo):
        """Caja que cubre TODOS los contactos de una cabeza, de una pieza.

        No vale un pad por contacto: la cabeza lleva varios contactos y entre
        dos pads contiguos queda un hueco de una decima que M1.2a denuncia. Hay
        que taparlos con una sola forma.
        """
        x0 = min(b.left for b in grupo) - ENC
        x1 = max(b.right for b in grupo) + ENC
        y0 = min(b.bottom for b in grupo) - ENC
        y1 = max(b.top for b in grupo) + ENC
        return x0, y0, x1, y1

    refs = []
    for i in range(n):
        ref = c.add_ref(seg)
        ref.dmovey(snap(i * paso))
        refs.append(ref)

    #  Metal1 sobre los contactos de cada extremo y las tiras del zigzag. El
    #  PCell deja los contactos pero no el metal, asi que hay que ponerlo.
    x_izq = snap(min(b.center().x for b in izq))
    x_der = snap(max(b.center().x for b in der))

    #  El metal1 se acumula en una Region y se emite YA FUNDIDO. Dibujarlo como
    #  rectangulos sueltos deja poligonos distintos que se tocan de canto, y ahi
    #  `space` con metrica euclidiana ve una pareja de aristas a distancia cero
    #  y la denuncia como M1.2a: no son dos formas cerca, es una forma mal
    #  cosida. Con 0.30 de tira salian 87 violaciones y con 0.40 subian a 705.
    U = 1.0 / c.kcl.layout.dbu

    def caja(x0, y0, x1, y1):
        return kdb.Box(int(round(x0 * U)), int(round(y0 * U)),
                       int(round(x1 * U)), int(round(y1 * U)))

    m1 = kdb.Region()
    cabezas = [envolvente(izq), envolvente(der)]
    #  La toma de sustrato va en su propia region, que NO se fusiona con la de
    #  las cabezas: si acabaran en el mismo poligono estariamos justo donde
    #  estabamos. Se emite aparte.
    m1_tomas = kdb.Region()
    toma = envolvente(de_sustrato) if de_sustrato else None
    for i in range(n):
        dy = snap(i * paso)
        for x0, y0, x1, y1 in cabezas:
            m1.insert(caja(snap(x0), snap(y0 + dy), snap(x1), snap(y1 + dy)))
        if toma:
            x0, y0, x1, y1 = toma
            m1_tomas.insert(caja(snap(x0), snap(y0 + dy), snap(x1), snap(y1 + dy)))
    for i in range(n - 1):
        #  zigzag: los pares se unen por la derecha y los impares por la izquierda
        x = x_der if i % 2 == 0 else x_izq
        y0 = snap(contactos[0].center().y + i * paso)
        y1 = snap(contactos[0].center().y + (i + 1) * paso)
        m1.insert(caja(x - STRAP / 2, y0, x + STRAP / 2, y1))
    m1.merge()
    m1_tomas.merge()
    for region in (m1, m1_tomas):
        for pol in region.each_merged():
            c.add_polygon([(pt.x / U, pt.y / U) for pt in pol.each_point_hull()],
                          layer=L["metal1"])

    #  Los dos terminales que quedan libres: el izquierdo del primer segmento y
    #  el que sobre en el ultimo, segun si n es par o impar.
    y0 = snap(contactos[0].center().y)
    yN = snap(contactos[0].center().y + (n - 1) * paso)
    #  De que lado queda libre el ultimo segmento lo decide el ULTIMO zigzag, que
    #  es el `i = n - 2`: si es par une por la derecha (y entonces el que sobra es
    #  el izquierdo) y si es impar une por la izquierda (sobra el derecho). O sea
    #  que depende de la paridad de `n`, no de la de `n - 1`.
    #
    #  Estaba justo al reves, y con `n = 5` daba el izquierdo: ahi el zigzag `i=3`
    #  ya habia unido las cabezas 3 y 4, asi que `term1` no era un extremo libre
    #  sino un nodo INTERNO de la cadena. La resistencia quedaba conectada por
    #  medio, con el ultimo segmento colgando, y el extremo de verdad --la cabeza
    #  derecha del segmento 4, que se ve sola en la geometria-- sin conectar a
    #  nada. Se comprueba mirando las formas de metal1 del propio serpentin: las
    #  dos que quedan sueltas (de 0.90 de alto, sin tira de zigzag) son los dos
    #  terminales, y con n=5 son la izquierda de abajo y la DERECHA de arriba.
    x_fin = x_izq if n % 2 == 0 else x_der
    c.info["term0"] = (x_izq, y0)
    c.info["term1"] = (x_fin, yN)
    c.info["n_seg"] = n
    c.info["largo_seg"] = largo
    c.name = nombre
    return c


# --- colocacion en el canal entre las dos filas -------------------------------

#: Margen del serpentin a los bordes del canal.
CANAL_MARGEN = 0.6
#: Cuanto se deja libre a cada lado de la celda al plegar. Es una PREFERENCIA
#: estetica, no una regla: no hay ningun DRC detras. Por eso la busqueda puede
#: bajar hasta BORDE_MIN cuando la geometria aprieta -- con 2.0 fijo, el
#: serpentin de OPAM_LIN_flat (79.28 um de ancho) no cabia a la izquierda del
#: dedo de nwell que empieza en x=80.82: quedaban 1.54 um y hacian falta 2.0,
#: asi que fallaban las 247.000 posiciones probadas.
BORDE = 2.0
#: Margen minimo al borde cuando no hay sitio de sobra.
BORDE_MIN = 0.6
#: Paso de la busqueda de posicion. A GRID*4 (0.02 um) salian 905 posiciones en
#: x por 273 en y y cada una cuesta varias operaciones de region: la corrida se
#: iba a diez minutos. 0.1 um es fino de sobra frente a las distancias que se
#: comprueban (0.23 de M1.2a) y sigue cayendo en la rejilla de 0.005.
PASO_BUSQUEDA = 0.1
#: Lado de la via y del pad de cada nivel, como en caps.py.
VIA = 0.26
PAD_VIA = 0.40
#  Media caja que tiene que quedar libre alrededor de un terminal para que su
#  pila no moleste a lo que ya hay: medio pad (0.20) mas la separacion que pide
#  M2.2a (0.28). V1.2a pide 0.26 entre vias, que con esto sale de sobra.
HOLGURA = PAD_VIA / 2 + 0.28
#: Distancia minima, medida desde el EJE del trunk de un puerto de senal, a la
#: que puede pasar el cruce de metal3 de una resistencia. La suma, de dentro
#: hacia fuera: medio pad de la plataforma del puerto (0.20) + el hueco que esa
#: plataforma le exige a cualquier metal3 ajeno (`power._LAND_CLEAR` = 0.47, que
#: es el espaciado 0.28 mas media anchura del cable del router, 0.19) + media
#: anchura del propio cruce (0.15). Da 0.82, y se redondea a 0.85.
#:
#: No se importa `_LAND_CLEAR` de `power` a proposito: `power` importa de `caps`
#: y esto crearia una dependencia cruzada por una constante. Si aquel cambia,
#: este numero hay que revisarlo -- por eso queda escrito el desglose.
#:
#: Medido: con 0.62 el cruce caia a 0.32 um del trunk de INN y ese puerto se
#: quedaba sin acceso en metal3, con sus 19 huecos libres y ninguno servible.
BANDA_PUERTO = 0.85

#: Banda limpia de metal2 que necesita el terminal de un serpentin para bajar al
#: canal: su pad de via en metal2 (`PAD_VIA`, 0.40) mas el espaciado de `M2.2a`
#: (0.28) a cada lado. Sale 0.96, y es LA cifra que decide si la resistencia se
#: puede colocar o no.
#:
#: Por que importa tanto: los trunks son barras horizontales que cruzan el canal
#: entero, asi que una `y` ocupada por un trunk no la libera ninguna `x`. El
#: terminal solo cabe donde no hay trunk. Y el router REPARTE los trunks por
#: todo el canal (`routing`: paso = banda / (pistas + 1)), asi que hacer el canal
#: mas alto no abre hueco: separa los trunks, si, pero tambien los mueve, y el
#: hueco entre ejes crecia de 1.19 a 1.25 mientras hacian falta 0.96 + 0.38 de
#: pad de via = 1.34.
#:
#: Medido en `OPAM_LIN_flat`: de las 11495 posiciones probadas, **9783 morian en
#: la caja del terminal** y ninguna pasaba. Se habia leido como un problema de
#: ancho -- "el serpentin mide 78.53 um y solo quedan 1.69 um de ventana antes
#: del brazo de nwell" -- y no lo era: el pozo solo rechazaba 45. Plegar mas la
#: resistencia (`s=10`) no habria arreglado nada.
#:
#: La solucion no es el paso sino el reparto: el canal se dimensiona como
#: trunks **mas** serpentin (no el maximo de los dos) y el router se queda con su
#: parte, dejando la del serpentin limpia. Ver `placement.build_layout` (`band`)
#: y `routing.route_layout` (`reservado`).
BANDA_TERMINAL = 2 * HOLGURA


def snap2(v: float) -> float:
    """Redondea a 0.01 um: el DOBLE de la rejilla, y hace falta que sea el doble.

    El PCell de resistencia dibuja la tira CENTRADA en el origen, o sea con los
    bordes en +-l_res/2. Con `l_res` en la rejilla de 5 nm pero multiplo IMPAR de
    ella, la mitad cae a 2.5 nm y se lleva fuera de rejilla las seis capas de
    golpe -- sab, poly2, pplus, contact, resistor y res_mk -- porque todas se
    miden desde ese borde. Con multiplo de 10 nm la mitad siempre cae en rejilla.

    Se comprobo midiendo el PCell: l_res=76.455 saca las seis capas descuadradas
    y l_res=76.450 sale limpio.
    """
    return round(v / (2 * GRID)) * (2 * GRID)


def _plan(dev, ancho_util: float):
    """Cuantas tiras y de que largo, para que el serpentin quepa a lo ancho.

    Se pliega ANCHO Y PLANO, no alto y estrecho: el serpentin va metido en el
    canal de ruteo entre la fila P y la fila N, asi que lo que hay que gastar es
    ancho -- que la celda ya tiene -- y no alto, que es lo caro. Con la banda
    lateral de antes la celda pasaba de 2777 a 5387 um2; asi solo crece el canal.
    """
    #  A la rejilla de 5 nm, y aqui, no al dibujar: la longitud sale de una
    #  cuenta de resistencia del esquematico (76.4536 um para 1.2 Mohm) y no
    #  tiene por que caer en rejilla. Si no se redondea, TODA la geometria que
    #  cuelga de ella queda descuadrada y saltan 90 OFFGRID de contact, pplus,
    #  poly2, sab, resistor y res_mk. Redondear 76.4536 a 76.455 mueve la
    #  resistencia un 0.002 %, muy por debajo de la tolerancia del proceso.
    ancho = snap2(max(dev.R_width_um, ANCHO_MIN))
    n_serie = int(float(dev.params.get("s", "1")))
    largo_seg = snap2(dev.R_length_um)
    #  El esquematico ya dice en cuantos segmentos esta partida (el multiplicador
    #  `s` del modelo), asi que el layout usa EXACTAMENTE esos: es lo que hace
    #  que esquematico y silicio describan lo mismo, incluida la correccion de
    #  extremo que el modelo aplica una vez por segmento.
    paso = ancho + 0.8 + HUECO
    return n_serie, largo_seg, ancho, n_serie * paso


#: Margen vertical EXTRA de canal, por encima de lo que el serpentin mide, para
#: que `place_resistors` pueda deslizarlo en y buscando hueco para sus
#: terminales. Sin el, el serpentin queda clavado contra el techo del canal y su
#: terminal de abajo cae donde caiga -- y si cae entre dos trunks no hay ninguna
#: x que lo salve, porque los trunks son barras horizontales. Con 2.5 um cabe
#: mas de un paso de trunk (0.835), que es lo que hace falta para saltar de un
#: carril al siguiente. Cuesta 2.5 um de alto de celda: barato comparado con
#: quedarse sin la resistencia.
#:
#: Subido de 2.5 a 5.0 al tumbar los MIM: la celda se acorto 6.8 um y el canal
#: quedo mas apretado, y con 3.0 um utiles las 905 x 148 posiciones probadas
#: fallaban todas. Los dos terminales van a 9 um fijos uno de otro y cada puerto
#: de senal prohibe una banda de 1.7 um (BANDA_PUERTO a cada lado), asi que hace
#: falta recorrido para encontrar el hueco donde caben los dos a la vez.
#:
#: **Y bajado de 5.0 a 2.0 al medirlo**, que es lo que habia que hacer desde el
#: principio: los 5.0 estaban puestos a ojo. Desde que el canal se dimensiona
#: como trunks **mas** serpentin y el router se queda solo con su parte
#: (§11.0.1b), la banda del serpentin nace limpia y el terminal ya no tiene que
#: ir a buscar un hueco entre trunks. Barrido de 3.0 a 0.0 en `OPAM_LIN_flat`:
#:
#:     BUSQUEDA_Y   3.0   2.5   2.0   1.5   1.0   0.5   0.0
#:     lo que baja  0.40  0.40  0.40  0.40  0.40  0.40  0.40   <- SIEMPRE 0.40
#:     alto celda  47.57 47.07 46.57 46.07 45.57 45.07 44.57
#:
#: La resistencia se coloca en los siete casos, con `res_mk` exacto y sin dejar
#: puertos sin acceso. O sea que **sobra casi todo**, y cada micra reservada de
#: mas es una micra de alto de celda.
#:
#: Se deja en 2.0 y no en 0.4: lo que hay que cubrir no es lo que baja HOY sino
#: lo que podria tener que bajar otra geometria, y el peor caso realista es
#: esquivar la banda prohibida de un puerto de senal, que mide 1.7 um
#: (`BANDA_PUERTO` a cada lado). 2.0 la cubre entera; 1.0 no.
BUSQUEDA_Y = 2.0


def altura_necesaria(resistors, ancho_util: float) -> float:
    """Alto de canal que hace falta para meter todos los serpentines."""
    alto = 0.0
    for dev in resistors:
        if dev.R_width_um < ANCHO_MIN - 1e-9:
            continue
        alto += _plan(dev, ancho_util)[3] + CANAL_MARGEN + BUSQUEDA_Y
    return alto + CANAL_MARGEN if alto else 0.0


#: Recorrido en x que se le deja al serpentin por encima de lo que mide. No es
#: cortesia: su metal1 son dos columnas rigidas, separadas lo que mide la tira
#: (76.45 um), y el canal esta cruzado por decenas de stubs verticales de metal1
#: que dejan corredores libres de entre 0.6 y 3 um. Las DOS columnas tienen que
#: caer en corredor a la vez, asi que hace falta recorrido para encontrar la
#: coincidencia. Medido: con el serpentin encajonado, de 12749 posiciones solo
#: 976 pasaban el metal1, y todas ellas caian ya sobre el pozo.
HOLGURA_X = 4.0


def ancho_necesario(resistors, ancho_util: float = 0.0) -> float:
    """Ancho que hay que dejar libre de POZO a la izquierda de la fila `span`.

    El serpentin no puede tocar el nwell: `NW.1b_MV` no penaliza el ancho del
    pozo sino que el marcador de resistencia CRUCE su borde, y el trozo que sale
    hereda el 1 um del cuerpo resistivo, asi que siempre incumple. Las dos
    salidas legales son que el marcador quede entero fuera o entero dentro, y
    con 79 um de serpentin "entero dentro" no existe.

    El pozo de la fila `span` -- el dispositivo de canal largo que va a caballo
    de las dos filas -- baja por todo el canal, asi que parte el sitio en dos y
    la resistencia tiene que caber en el trozo de la izquierda. Cuando no cabe,
    lo barato es EMPUJAR esa fila a la derecha: la celda se ensancha unas micras
    (a 48.91 um de alto, 3 um de ancho son 147 um2) mientras que estrechar el
    serpentin plegandolo mas cuesta el doble de alto de banda -- con `s=10` la
    celda pasaria de 48.9 a unos 60, o sea 1100 um2 -- y ademas es cambio de
    esquematico, porque `s` fija cuantas veces aplica el modelo la correccion de
    extremo.
    """
    ancho = 0.0
    for dev in resistors:
        if dev.R_width_um < ANCHO_MIN - 1e-9:
            continue
        n, largo_seg, anc, _alto = _plan(dev, ancho_util)
        comp = serpentin(dev.model, anc, largo_seg * n, n, f"{dev.name}_medida")
        ancho = max(ancho, comp.dxsize)
    return ancho + 2 * BORDE_MIN + HOLGURA_X if ancho else 0.0


def _pila(top, L, x, y, desde="metal1", hasta="metal2"):
    """Pila de vias de `desde` a `hasta` en (x, y), con su pad en cada nivel."""
    niveles = ["metal1", "via1", "metal2", "via2", "metal3"]
    i0, i1 = niveles.index(desde), niveles.index(hasta)
    for n in niveles[i0:i1 + 1]:
        lado = VIA if n.startswith("via") else PAD_VIA
        top.add_polygon([(x - lado / 2, y - lado / 2), (x + lado / 2, y - lado / 2),
                         (x + lado / 2, y + lado / 2), (x - lado / 2, y + lado / 2)],
                        layer=L[n])


def place_resistors(lay, resistors) -> None:
    """Coloca los serpentines en el canal, ya ruteado.

    Va DESPUES de rutear, como los condensadores, para no depender de donde
    caigan los trunks. Lo que no se pueda colocar va a `lay.res_failed` con el
    motivo. Nunca se calla: una resistencia que falte no la ve **ni el DRC ni el
    LVS**, porque la netlist de referencia sale del mismo aplanado y los dos
    saldrian limpios describiendo un circuito que no es el del esquematico.
    """
    if not resistors:
        return
    import klayout.db as kdb
    from coil_layout.caps import _free_points, _region

    gf180 = get_pdk_module("gf180")
    top = lay.component
    L = gf180.layer
    #  `channel_y` es el CENTRO del canal, no su borde: el canal va de
    #  `channel_y - channel_h/2` a `channel_y + channel_h/2`. Colgar el
    #  serpentin del centro hacia abajo lo metia entero en la fila N1 -- y eso no
    #  se ve como un solape cualquiera, porque el marcador `res_mk` cubriendo
    #  poly de PUERTA hace que el deck lea los transistores como cuerpo de
    #  resistencia: 1222 violaciones de SB/HRES/LRES/PL/CO/NP de golpe.
    techo = snap(lay.channel_y + lay.channel_h / 2 - CANAL_MARGEN)
    #  El suelo NO es el fondo del canal: es el fondo de la banda que se reservo
    #  para los serpentines al dimensionarlo. Por debajo empieza el reparto de
    #  trunks del router, y ahi no hay nada que buscar -- el terminal necesita
    #  0.96 um limpios de metal2 y entre trunks no los hay (BANDA_TERMINAL). Si
    #  el canal no viene con reserva se cae al comportamiento de antes, que es lo
    #  que quieren los bloques sin resistencia.
    reservado = lay.channel_reserved.get("A", 0.0)
    suelo = snap(techo - reservado + CANAL_MARGEN) if reservado else \
        snap(lay.channel_y - lay.channel_h / 2 + CANAL_MARGEN)
    y_libre = techo
    #  Se mide el metal2 que YA hay -- trunks, risers de los condensadores,
    #  accesos de puerto -- para no pisarlo. Por eso este paso va el ultimo de
    #  los que cuelgan del trunk: a la resistencia le basta un punto de via,
    #  mientras que un MIM necesita 20 um seguidos, asi que la que tiene que
    #  ceder es esta. Colocandola primero dejaba a los dos MIM y a dos puertos
    #  sin sitio en el trunk de OUT.
    m2 = _region(top, L["metal2"])
    #  Huella de los condensadores MIM. Ni el terminal ni el aterrizaje pueden
    #  caer debajo, y no es una regla de DRC: es que **la extraccion no conecta
    #  ahi**. Medido -- el mismo bloque sin los MIM saca la cadena entera de
    #  `G_OUT_P` a `OUT`, y con ellos, con el terminal bajo una placa, el ultimo
    #  tramo acaba en una net suelta (`$263`) mientras el metal2 que tiene encima
    #  si es `OUT`: el deck ve dos nets distintas en el mismo punto. El DRC daba
    #  0 y el layout parecia bueno. Se aparta el terminal y ya.
    mim = (_region(top, L["metal4"]) + _region(top, L["metal5"])
           + _region(top, L["fusetop"])).merged()
    usados: list[kdb.DBox] = []

    def bajo_mim(x, y) -> bool:
        caja = kdb.DBox(x - HOLGURA, y - HOLGURA, x + HOLGURA, y + HOLGURA)
        return not (mim & kdb.Region(caja.to_itype(top.kcl.layout.dbu))).is_empty()

    def hueco(net, cerca_de):
        """Punto libre del trunk de `net`, el mas cercano en x a `cerca_de`."""
        libres = [(x, y) for x, y in _free_points(lay.trunks.get(net), m2)
                  if not any(b.contains(kdb.DPoint(x, y)) for b in usados)
                  and not bajo_mim(x, y)]
        if not libres:
            return None
        return min(libres, key=lambda p: abs(p[0] - cerca_de))

    for dev in resistors:
        ancho = dev.R_width_um
        if ancho < ANCHO_MIN - 1e-9:
            lay.res_failed.append(
                (dev.name, f"ancho {ancho} um < {ANCHO_MIN}, que es lo que pide HRES.2 "
                           f"para la resistencia de alta hoja; corrigelo en el esquematico"))
            continue
        n, largo_seg, ancho, alto = _plan(dev, lay.width)
        comp = serpentin(dev.model, ancho, largo_seg * n, n, f"{dev.name}_serp")
        if comp.dxsize > lay.width + 2 * BORDE:
            lay.res_failed.append(
                (dev.name, f"el serpentin mide {comp.dxsize:.1f} um de ancho y la celda "
                           f"{lay.width:.1f}: hacen falta mas pliegues"))
            continue
        #  Antes de dibujar nada: si no cabe DENTRO del canal no se coloca. Una
        #  resistencia que falte se nota (va a `res_failed` y el flujo lo grita);
        #  una que se salga por abajo pasa el LVS y arruina el DRC.
        if comp.dysize > y_libre - suelo + 1e-9:
            lay.res_failed.append(
                (dev.name, f"el serpentin mide {comp.dysize:.2f} um de alto y en el canal "
                           f"quedan {max(y_libre - suelo, 0.0):.2f}: sube el canal"))
            continue
        dy = snap(y_libre - comp.dymax)

        #  El dx no se fija a BORDE y ya: hay que buscar uno donde los DOS
        #  terminales caigan en hueco. Con el fijo, el terminal izquierdo
        #  aterrizaba justo encima de un stub de ruteo que ya estaba ahi y
        #  sacaba M2.1, M2.2a y V1.2a -- su via1 quedaba a 0.105 um del via1 del
        #  stub cuando V1.2a pide 0.26. Se desliza el serpentin a lo largo del
        #  canal, que para eso sobra ancho, hasta dar con un sitio limpio.
        #  El trunk de la PROPIA net no estorba: un terminal encima del trunk al
        #  que se va a conectar no es una violacion, es la conexion. Y hay que
        #  descontarlo o no hay solucion: los trunks son barras horizontales que
        #  cruzan el canal entero, asi que si la `y` de un terminal cae sobre uno
        #  no existe NINGUNA x que lo libre -- deslizar en x no sirve de nada.
        dbu = top.kcl.layout.dbu
        propios = kdb.Region()
        for net in (dev.nodes["r0"], dev.nodes["r1"]):
            for x0, x1, ty_, alto in (lay.trunks.get(net) or []):
                caja = kdb.DBox(x0, ty_ - alto / 2, x1, ty_ + alto / 2)
                propios.insert(caja.to_itype(dbu))
        estorbo = (m2 + _region(top, L["via1"])) - propios.merged()

        #  El METAL1 del serpentin tambien hay que mirarlo, y no solo alrededor
        #  de los terminales: el serpentin lleva metal1 en las cinco cabezas de
        #  contacto y en todas las tiras del zigzag, a lo largo de sus 76 um, y
        #  el canal esta cruzado por 67 straps verticales de metal1. Dibujarlo a
        #  ciegas fundio 5.00 um2 de metal1 con un strap ya existente y **corto
        #  OUT contra VSS**. No lo vio el DRC -- dos metales de nets distintas
        #  que se tocan no violan ninguna regla, porque tocarse es lo que hace un
        #  cable -- y lo canto el LVS: `OUT|VSS` en las 77 ocurrencias.
        #  Confirmado por diferencia entre el GDS con resistencia y sin ella.
        m1_previo = _region(top, L["metal1"])
        m1_serp = kdb.Region(comp.kdb_cell.begin_shapes_rec(
            top.kcl.layout.layer(*L["metal1"]))).merged()
        #  Se ensancha por el espaciado de M1.2a (0.23): asi el mismo chequeo
        #  cubre el corto Y la violacion de separacion.
        m1_serp_holgado = m1_serp.sized(int(round(0.23 / dbu)))

        #  Y el POZO. `NW.1b_MV` dice "ancho minimo de nwell COMO RESISTENCIA:
        #  2 um": el marcador de resistencia sobre un trozo de nwell hace que el
        #  deck lea ese pozo como cuerpo resistivo. El pozo en L del dispositivo
        #  a caballo baja por el canal en un dedo estrecho (0.75 um en x), y al
        #  cruzarlo el serpentin salieron 10 violaciones, dos por segmento. Se
        #  mide sobre la capa `resistor`, que es la que miran las reglas HRES.
        nwell_previo = _region(top, L["nwell"])
        res_serp = kdb.Region(comp.kdb_cell.begin_shapes_rec(
            top.kcl.layout.layer(*L["resistor"]))).merged()

        #  Bandas de `y` PROHIBIDAS: las de los trunks de los puertos de senal.
        #  El salto al trunk cruza el canal en metal3 a la altura del terminal, o
        #  sea que si el terminal cae a la altura del trunk de un puerto, ese
        #  cable corre POR ENCIMA de todo el trunk y lo deja sin sitio donde
        #  aterrizar. Paso de verdad: `INN` acababa con 19 huecos libres en su
        #  trunk y ninguno servible, y el bloque salia con un puerto sin acceso.
        #  No es una violacion de DRC -- por eso hace falta prohibirlo aqui: el
        #  DRC de ese layout daba 0.
        prohibidas = []
        for net in lay.ports:
            if net in lay.power_ports or net in (dev.nodes["r0"], dev.nodes["r1"]):
                continue
            for _x0, _x1, ty_, _alto in (lay.trunks.get(net) or []):
                prohibidas.append((ty_ - BANDA_PUERTO, ty_ + BANDA_PUERTO))

        motivos = {"banda": 0, "terminal": 0, "mim": 0, "metal1": 0,
                   "nwell": 0, "ok": 0}

        def despejado(dx_prueba, dy_prueba):
            #  Primero los dos chequeos baratos (bandas y cajas de terminal) y
            #  solo si pasan, el caro: la huella de metal1 entera.
            for t in ("term0", "term1"):
                px, py = comp.info[t]
                px, py = snap(px + dx_prueba), snap(py + dy_prueba)
                if any(lo <= py <= hi for lo, hi in prohibidas):
                    motivos["banda"] += 1; return False
                caja = kdb.DBox(px - HOLGURA, py - HOLGURA, px + HOLGURA, py + HOLGURA)
                if not (estorbo & kdb.Region(caja.to_itype(dbu))).is_empty():
                    motivos["terminal"] += 1; return False
                if bajo_mim(px, py):
                    motivos["mim"] += 1; return False
            tr = kdb.Trans(kdb.Vector(int(round(dx_prueba / dbu)),
                                      int(round(dy_prueba / dbu))))
            if not (m1_serp_holgado.transformed(tr) & m1_previo).is_empty():
                motivos["metal1"] += 1; return False
            if not (res_serp.transformed(tr) & nwell_previo).is_empty():
                motivos["nwell"] += 1; return False
            motivos["ok"] += 1
            return True

        #  Hay que buscar en las DOS direcciones, y la que de verdad importa es
        #  la Y. Los trunks son barras horizontales, asi que un terminal
        #  aprisionado entre dos de ellas no se libera moviendose de lado: se
        #  midio a `term0` metido en un hueco de 0.505 um entre metal2 a y=9.58 y
        #  a y=10.085, cuando su pad necesita 0.40 + 2x0.28 = 0.96. Con solo
        #  busqueda en x fallaban las 905 posiciones probadas. El margen vertical
        #  para poder moverse lo reserva `altura_necesaria` (ver BUSQUEDA_Y).
        #  Se barre desde BORDE_MIN, no desde BORDE: el margen bonito se
        #  intenta, pero no se muere por el.
        margen_x = lay.width - comp.dxsize - 2 * BORDE_MIN
        paso = PASO_BUSQUEDA
        xs = [snap(-comp.dxmin + BORDE_MIN + k * paso)
              for k in range(max(int(margen_x / paso), 0) + 1)]
        #  Cuanto se puede bajar el serpentin sin salirse por el suelo del canal.
        #  OJO: `dy` es un DESPLAZAMIENTO, no una coordenada, asi que restarle
        #  `suelo` no significa nada. La holgura es lo que sobra del canal una vez
        #  metido el serpentin: (techo - suelo) - alto. Con la cuenta mal salia 0
        #  y la busqueda en y no se hacia, aunque el canal tuviera sitio.
        holgura_y = max((techo - suelo) - comp.dysize, 0.0)
        ys = [snap(dy - k * paso) for k in range(int(holgura_y / paso) + 1)]
        sitio = next(((x, y) for y in ys for x in xs if despejado(x, y)), None)
        if sitio is None:
            #  El reparto de rechazos, no solo el hecho de que fallo. Los
            #  chequeos van en cascada, asi que se lee en orden: el primero que
            #  descarta mucho tapa a los siguientes, y el ultimo con cuenta baja
            #  es el que de verdad esta bloqueando. Sin esto solo se sabia "no
            #  cabe", que no dice que aflojar.
            lay.res_failed.append(
                (dev.name, f"no hay sitio en el canal: {len(xs)} x {len(ys)} posiciones "
                           f"probadas en {margen_x:.1f} x {len(ys) * paso:.1f} um. "
                           f"Rechazos en cascada -> banda de puerto: {motivos['banda']}, "
                           f"caja de terminal (metal2/via1): {motivos['terminal']}, "
                           f"bajo un MIM: {motivos['mim']}, "
                           f"huella de metal1: {motivos['metal1']}, "
                           f"pozo (NW.1b_MV): {motivos['nwell']}"))
            continue
        dx, dy = sitio
        ref = top.add_ref(comp)
        ref.dmovex(dx)
        ref.dmovey(dy)
        #  Los siguientes se apilan por debajo de este.
        y_libre = snap(y_libre - comp.dysize - CANAL_MARGEN)

        fallo = False
        for term, net in (("term0", dev.nodes["r0"]), ("term1", dev.nodes["r1"])):
            tx, ty = comp.info[term]
            tx, ty = snap(tx + dx), snap(ty + dy)
            punto = hueco(net, tx)
            if punto is None:
                lay.res_failed.append(
                    (dev.name, f"la net {net} no tiene hueco libre en su trunk; "
                               f"los condensadores y los puertos ya lo han ocupado"))
                fallo = True
                break
            #  El salto hasta el trunk va por METAL3, no por metal2. Es lo unico
            #  que funciona: el canal esta lleno de stubs verticales de metal2
            #  subiendo de la fila al trunk, asi que un cable horizontal de
            #  metal2 a la altura del terminal los cruza todos -- daba 44
            #  violaciones de M2.2a en las dos lineas de y de los dos terminales.
            #  metal3 esta vacio en este flujo y la pila via2 ya esta probada en
            #  `caps.py`, asi que se cruza por encima y se baja al lado del trunk.
            xtr, ytr = punto
            usados.append(kdb.DBox(xtr - 0.4, ytr - 0.4, xtr + 0.4, ytr + 0.4))
            _pila(top, L, tx, ty, "metal1", "metal3")     # sube en el terminal
            _pila(top, L, xtr, ytr, "metal2", "metal3")   # baja sobre el trunk
            #  Se anota **solo el terminal**, no el aterrizaje, para que los
            #  condensadores no pongan una placa encima: con el MIM delante la
            #  extraccion no conecta esa pila.
            #
            #  Y solo el terminal a proposito. Lo que se midio roto es la pila
            #  que arranca en metal1 (la cabeza del serpentin): con la placa
            #  encima, su metal1 quedaba en una net suelta mientras el metal2
            #  que tenia justo arriba si era la net buena. El aterrizaje sobre
            #  el trunk no lleva via1 --va de metal2 a metal3-- y ese tramo si
            #  se extrae bien debajo de un MIM; de hecho los risers de los
            #  propios condensadores hacen exactamente eso.
            #
            #  Vetar los dos costaba caro y en la moneda equivocada: los cuatro
            #  puntos dejaban a los MIM sin sitio para ponerse TUMBADOS y uno
            #  acababa de pie, con sus 25 um en vertical fijando la altura de la
            #  celda -- 55.16 um en vez de 49.57.
            lay.res_terminals.append((tx, ty))
            top.add_polygon([(min(xtr, tx) - 0.15, ty - 0.15), (max(xtr, tx) + 0.15, ty - 0.15),
                             (max(xtr, tx) + 0.15, ty + 0.15), (min(xtr, tx) - 0.15, ty + 0.15)],
                            layer=L["metal3"])
            top.add_polygon([(xtr - 0.15, min(ty, ytr)), (xtr + 0.15, min(ty, ytr)),
                             (xtr + 0.15, max(ty, ytr)), (xtr - 0.15, max(ty, ytr))],
                            layer=L["metal3"])
        if not fallo:
            lay.res_placed.append((dev.name, n, largo_seg, ancho))
