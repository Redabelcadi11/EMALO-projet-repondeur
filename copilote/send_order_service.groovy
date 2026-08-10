import fr.infologic.core.communication.RemoteServiceFactoryImpl
import fr.infologic.core.services.search.SearchParam
import fr.infologic.outils.persistance.IK
import fr.infologic.achatsventes.services.util.InfoEnteteDTO
import fr.infologic.ventes.services.search.CliLivSearcherService
import fr.infologic.ventes.services.search.ArticleSearcherService
import fr.infologic.ventes.services.commande.CommandeService
import fr.infologic.ventes.services.chargLig.ChargLigService
import fr.infologic.ventes.services.validcde.ValidCdeDTO
import fr.infologic.ventes.services.validcde.ValidCdeService
import fr.infologic.core.services.print.PrintRequest
import java.text.SimpleDateFormat

fr.infologic.hibernate.proxy.BytecodeProviderImpl.setup()

if (args.length < 7 || ((args.length - 4) % 3) != 0) {
    throw new IllegalArgumentException("Usage: cookie clientCode yyyy-MM-dd orderRef productCode qty unit [productCode qty unit...]")
}

def cookie = args[0]
def clientCode = args[1]
def dateFormat = new SimpleDateFormat("yyyy-MM-dd")
dateFormat.setLenient(false)
def dateLiv = dateFormat.parse(args[2])
def orderRef = args[3]
def today = new Date()

def factory = new RemoteServiceFactoryImpl()
factory.setUrl(new URL("http://172.16.213.101:8080/ventes/ProxyServlet"))
factory.setCompression(1)
factory.setThreadRequestProperty("X-Prop-LongServiceCall", "1")
factory.setThreadRequestProperty("X-Prop-SaisieId", "")
factory.initialize()

def injectCookie = {
    def httpClientField = factory.getClass().getDeclaredField("httpClient")
    httpClientField.accessible = true
    def httpClient = httpClientField.get(factory)
    def cookieManagerField = httpClient.getClass().getDeclaredField("cookieManager")
    cookieManagerField.accessible = true
    def cookieManager = cookieManagerField.get(httpClient)
    def httpCookie = new java.net.HttpCookie("JSESSIONID", cookie.replace("JSESSIONID=", ""))
    httpCookie.path = "/ventes"
    cookieManager.cookieStore.add(new URI("http://172.16.213.101:8080/ventes"), httpCookie)
}

def ikOf = { obj -> obj == null ? null : obj.getIk() }

def safeSet = { target, methodName, value ->
    try {
        target."${methodName}"(value)
        return true
    } catch (MissingMethodException ignored) {
        return false
    }
}

def buildInfo = { cde, cliIK ->
    def info = new InfoEnteteDTO()
    info.setModeSaisie(0)
    info.setDepotSoc(false)
    info.setSaisieDirect(true)
    info.setCdeEdi(false)
    info.setReactualisePrixOnChangeLigneFin(false)
    info.setCdeReliquatGenere(false)
    info.setMajTarNegoce(false)
    info.setTypPrg(1)
    info.setCtrlSaisieFromContrat(false)
    info.setModRechPerVal(0)
    info.setChargInfoCompta(false)
    info.setFirstPlancherDefault(false)
    info.setUseObjectifQualite(true)
    info.setGestAffichageContratCadencier(true)
    info.setReChargInfoCompta(false)
    info.setInitDto(true)
    info.setCdeEchantillon(false)
    info.setIgnoreRemisePlancherCA(false)
    info.setCliFourIK(cliIK)
    info.setCliFourFactIK(ikOf(cde.getCliFact()))
    info.setCliFourPayeurIK(ikOf(cde.getCliPayeur()))
    info.setCliFourCode(clientCode)
    info.setCliFourCodeRech(clientCode)
    info.setModArrondiPalette(-1)
    info.setChargStock(true)
    info.setChargStockAffichage(false)
    info.setChargDerCde(true)
    info.setChargInfoLecture(true)
    info.setChargInfoAchat(true)
    info.setChargLotDegagement(1)
    info.setChargEnAvant(1)
    info.setChargPromo(1)
    info.setDatRef(today)
    info.setDatRefPrix(today)
    info.setDatRefBlocage(today)
    info.setDatRefStock(today)
    info.setDatLiv(dateLiv)
    info.setDatDepart(dateLiv)
    info.setDatCde(today)
    info.setHeureCde(cde.getHeureCde())
    info.setHeureDepart(cde.getHeureDepart())
    info.setTriCad(cde.getTriCad())
    info.setSansQte(0)
    info.setSiteIK(ikOf(cde.getSiteExped()))
    info.setLieuIK(ikOf(cde.getLieuExped()))
    info.setTransportIK(ikOf(cde.getTransp()))
    info.setTypCdeSupervIK(ikOf(cde.getTypCdeSuperv()))
    info.setRepresentant1IK(ikOf(cde.getRepres1()))
    info.setGestSupervInfologic(cde.getGestSupervInfologic())
    info.setTypUPrep(cde.getTypUPrep())
    info.setTypReduct(cde.getTypReduct())
    info.setCdeMonnaie(fr.infologic.achatsventes.services.util.CdeMonnaie.buildCdeMonnaie(cde))
    info.setTaxe(cde.getTaxe())
    return info
}

try {
    injectCookie()
    def oper = new IK(242384929L)
    def cliParams = [
        new SearchParam("datRefBlocage", today),
        new SearchParam("datCde", today),
        new SearchParam("operateur", new ArrayList([oper])),
        new SearchParam("utilisateur", oper),
        new SearchParam("jour", Integer.valueOf(2)),
        new SearchParam("filtreEcran", Integer.valueOf(0)),
        new SearchParam("C_prospect", Integer.valueOf(2)),
    ] as SearchParam[]

    factory.setThreadRequestProperty("X-Prop-ServiceSource", "fr.infologic.ventes.client.searcher.CliLivReferenceSearcher.findByCode (CliLivReferenceSearcher.java:304)")
    def cliFound = ((CliLivSearcherService) factory.getService(CliLivSearcherService.ROLE)).getCliLivByCode(clientCode, cliParams, 1)
    if (!cliFound) throw new IllegalStateException("Client introuvable: ${clientCode}")
    def cliIK = cliFound[0]

    factory.setThreadRequestProperty("X-Prop-ServiceSource", "fr.infologic.ventes.client.modules.commandesfactures.commande.entetecmd.CommandeVentesForm.createCde (CommandeVentesForm.java:10707)")
    def dto = ((CommandeService) factory.getService(CommandeService.ROLE)).create(today, Short.valueOf((short)1036), cliIK, null, false, true, true, 0)
    def cde = dto.getCommande()
    cde.setDatLiv(dateLiv)
    cde.setDatDepart(dateLiv)
    cde.setDatFact(dateLiv)
    cde.setDatLivImperative(1)
    if (dateFormat.format(cde.getDatLiv()) != args[2] || dateFormat.format(cde.getDatDepart()) != args[2]) {
        throw new IllegalStateException("Date livraison/depart non appliquee: attendu=${args[2]} datLiv=${dateFormat.format(cde.getDatLiv())} datDepart=${dateFormat.format(cde.getDatDepart())}")
    }
    println("REQUESTED_DELIVERY_DATE=${args[2]}")
    def info = buildInfo(cde, cliIK)

    def artParams = [
        new SearchParam("typesRefExclus", new ArrayList([Integer.valueOf(5)])),
        new SearchParam("flagEtatFicheContext", Integer.valueOf(5)),
        new SearchParam("typesRefInclus", Collections.singleton(Integer.valueOf(0))),
    ] as SearchParam[]

    def lines = new ArrayList()
    def lineNo = 0L
    for (int i = 4; i < args.length; i += 3) {
        def productCode = args[i]
        def quantity = new com.ibm.icu.math.BigDecimal(args[i + 1])
        def unit = args[i + 2] ?: "UB"
        factory.setThreadRequestProperty("X-Prop-ServiceSource", "article lookup")
        def found = ((ArticleSearcherService) factory.getService(ArticleSearcherService.ROLE)).findByCode(productCode, artParams, true, false, false, true, true)
        if (!found) throw new IllegalStateException("Article introuvable: ${productCode}")
        def articleIK = ikOf(found[0])
        factory.setThreadRequestProperty("X-Prop-ServiceSource", "fr.infologic.achatsventes.client.modules.commandesfactures.configurabletable.util.CalculUtilLignes.getNewLine")
        def line = ((ChargLigService) factory.getService(ChargLigService.ROLE)).chargLig(info, articleIK, null, null)
        def ecrit = line.getCdeLigDtoEcriture()
        [
            "setQteUCde",
            "setCdeQteUBase",
            "setCdeQteUFact",
            "setCdeQteUElem",
            "setCdeQteUElemAppro",
            "setCdeQteULogisSuppl1",
            "setCdeQteULogisSuppl2",
            "setCdeQteUSousEmbal",
            "setCdeQteUSurEmbal",
            "setCdePoidsNet",
            "setCdePoidsBrut",
            "setCdePoidsTheo",
            "setPoidsNet",
            "setPoidsBrut",
            "setPoidsTheo",
            "setCdeVolume",
            "setVolume",
            "setCdeVolumeContenu",
            "setVolumeContenu",
            "setQteCdeEdi",
        ].each { methodName ->
            safeSet(ecrit, methodName, quantity)
        }
        ecrit.setuCdeEdi(unit)
        ecrit.setNumLig(lineNo)
        ecrit.setOrdreLig(lineNo + 1L)
        ecrit.setOrdreLigCde(lineNo)
        lines.add(line)
        lineNo++
        println("LINE=${productCode};QTY=${quantity};UNIT=${unit}")
    }

    def valid = new ValidCdeDTO()
    valid.setCommandeDTO(dto)
    valid.setListCdeLig(lines)
    valid.setLinesToDelete(new ArrayList())
    valid.setCdeGenere(false)
    valid.setTypCde(-1)
    valid.setUpdateCdeAchNegoce(true)
    valid.setGestModifCdeEnPrep(0)
    valid.setLockNewCde(false)
    valid.setValidCdeDtos(new ArrayList())

    def printRequests = new PrintRequest[1][0]
    def virtualKey = "virtual-" + UUID.randomUUID().toString().replace("-", "")
    factory.setThreadRequestProperty("X-Prop-ServiceSource", 'fr.infologic.ventes.client.modules.commandesfactures.commande.synthese.SyntheseVentesForm$ValidationHandler.valider (SyntheseVentesForm.java:4416)')
    def saveAux = new ArrayList(Collections.nCopies(lines.size(), null))
    def result = ((ValidCdeService) factory.getService(ValidCdeService.ROLE)).saveCdeBatch(valid, virtualKey, saveAux, printRequests)
    println("ORDER_NUMBER=${result}")
} finally {
    factory.dispose()
}
