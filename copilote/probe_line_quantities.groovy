import fr.infologic.core.communication.RemoteServiceFactoryImpl
import fr.infologic.core.services.search.SearchParam
import fr.infologic.outils.persistance.IK
import fr.infologic.achatsventes.services.util.InfoEnteteDTO
import fr.infologic.ventes.services.search.CliLivSearcherService
import fr.infologic.ventes.services.search.ArticleSearcherService
import fr.infologic.ventes.services.commande.CommandeService
import fr.infologic.ventes.services.chargLig.ChargLigService
import java.text.SimpleDateFormat

def guardCandidates = []
def workingDirectory = new File(System.getProperty('user.dir')).canonicalFile
guardCandidates.add(new File(workingDirectory, 'erp_write_guard.groovy'))
guardCandidates.add(new File(workingDirectory, 'copilote/erp_write_guard.groovy'))
if (workingDirectory.parentFile) guardCandidates.add(new File(workingDirectory.parentFile, 'copilote/erp_write_guard.groovy'))
def guardFile = guardCandidates.find { it.isFile() }
if (!guardFile) {
    throw new SecurityException("[ERP_WRITE_BLOCKED] diagnostic quantites: garde central introuvable")
}
def erpGuard = new GroovyShell().parse(guardFile)
erpGuard.assertErpWriteAllowed(guardFile.parentFile.parentFile, 'diagnostic appelant CommandeService.create')

fr.infologic.hibernate.proxy.BytecodeProviderImpl.setup()

def cookie = args[0]
def clientCode = args[1]
def productCode = args[2]
def dateFormat = new SimpleDateFormat("yyyy-MM-dd")
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

def dumpGetters = { label, obj ->
    println("### ${label}: ${obj?.getClass()?.name}")
    obj.getClass().methods.findAll { m ->
        m.parameterTypes.length == 0 && (
            m.name.toLowerCase().contains("qte") ||
            m.name.toLowerCase().contains("quant") ||
            m.name.toLowerCase().contains("unit") ||
            m.name.toLowerCase().contains("ucde") ||
            m.name.toLowerCase().contains("ufact") ||
            m.name.toLowerCase().contains("uelem") ||
            m.name.toLowerCase().contains("volume") ||
            m.name.toLowerCase().contains("poids")
        )
    }.sort { it.name }.each { m ->
        try {
            println("${m.name}=${m.invoke(obj)}")
        } catch (Throwable t) {
            println("${m.name}=<${t.class.name}>")
        }
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
    info.setDatRef(today)
    info.setDatRefPrix(today)
    info.setDatRefBlocage(today)
    info.setDatRefStock(today)
    info.setDatLiv(dateFormat.parse("2026-09-01"))
    info.setDatDepart(dateFormat.parse("2026-09-01"))
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

    factory.setThreadRequestProperty("X-Prop-ServiceSource", "probe client")
    def cliIK = ((CliLivSearcherService) factory.getService(CliLivSearcherService.ROLE)).getCliLivByCode(clientCode, cliParams, 1)[0]
    factory.setThreadRequestProperty("X-Prop-ServiceSource", "probe create")
    def dto = ((CommandeService) factory.getService(CommandeService.ROLE)).create(today, Short.valueOf((short)1036), cliIK, null, false, true, true, 0)
    def cde = dto.getCommande()
    cde.setDatLiv(dateFormat.parse("2026-09-01"))
    cde.setDatDepart(dateFormat.parse("2026-09-01"))
    cde.setDatFact(dateFormat.parse("2026-09-01"))
    def info = buildInfo(cde, cliIK)

    def artParams = [
        new SearchParam("typesRefExclus", new ArrayList([Integer.valueOf(5)])),
        new SearchParam("flagEtatFicheContext", Integer.valueOf(5)),
        new SearchParam("typesRefInclus", Collections.singleton(Integer.valueOf(0))),
    ] as SearchParam[]
    factory.setThreadRequestProperty("X-Prop-ServiceSource", "probe article")
    def articleIK = ikOf(((ArticleSearcherService) factory.getService(ArticleSearcherService.ROLE)).findByCode(productCode, artParams, true, false, false, true, true)[0])
    factory.setThreadRequestProperty("X-Prop-ServiceSource", "probe chargLig")
    def line = ((ChargLigService) factory.getService(ChargLigService.ROLE)).chargLig(info, articleIK, null, null)
    dumpGetters("line", line)
    dumpGetters("ecriture", line.getCdeLigDtoEcriture())
} finally {
    factory.dispose()
}
