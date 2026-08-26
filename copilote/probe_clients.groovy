import fr.infologic.core.communication.RemoteServiceFactoryImpl
import fr.infologic.core.services.search.SearchParam
import fr.infologic.outils.persistance.IK
import fr.infologic.ventes.services.search.CliLivSearcherService

fr.infologic.hibernate.proxy.BytecodeProviderImpl.setup()

def cookie = args[0]
def codes = args[1..-1]
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

try {
    injectCookie()
    def oper = new IK(242384929L)
    def params = [
        new SearchParam("datRefBlocage", today),
        new SearchParam("datCde", today),
        new SearchParam("operateur", new ArrayList([oper])),
        new SearchParam("utilisateur", oper),
        new SearchParam("jour", Integer.valueOf(2)),
        new SearchParam("filtreEcran", Integer.valueOf(0)),
        new SearchParam("C_prospect", Integer.valueOf(2)),
    ] as SearchParam[]
    factory.setThreadRequestProperty("X-Prop-ServiceSource", "fr.infologic.ventes.client.searcher.CliLivReferenceSearcher.findByCode (CliLivReferenceSearcher.java:304)")
    def svc = (CliLivSearcherService) factory.getService(CliLivSearcherService.ROLE)
    codes.each { code ->
        try {
            def found = svc.getCliLivByCode(code, params, 1)
            println("${found ? 'OK' : 'NO'}\t${code}\t${found ? found[0] : ''}")
        } catch (Throwable t) {
            println("ERR\t${code}\t${t.class.name}: ${t.message}")
        }
    }
} finally {
    factory.dispose()
}
