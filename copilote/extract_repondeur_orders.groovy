import fr.infologic.core.communication.RemoteServiceFactoryImpl
import fr.infologic.infoc.engine.api.filter.IFilter
import fr.infologic.infoc.engine.api.filter.InFilter
import fr.infologic.infoc.modele.TableauBordStat
import fr.infologic.infoc.services.infocentre.tableaubord.InfocentreTableauBordService
import fr.infologic.outils.persistance.IK
import fr.infologic.ventes.services.commande.CommandeService

import java.text.SimpleDateFormat

fr.infologic.hibernate.proxy.BytecodeProviderImpl.setup()

if (args.length < 7) {
  throw new IllegalArgumentException(
    'Usage: cookie headerTemplate lineTemplate dateFrom dateTo operator outputCsv [periodicLineTemplate]'
  )
}

def cookie = args[0]
def headerTemplatePath = args[1]
def lineTemplatePath = args[2]
def dateFromText = args[3]
def dateToText = args[4]
def operatorFilter = (args[5] ?: 'ES').trim().toUpperCase()
def outputCsv = new File(args[6])
def periodicLineTemplatePath = args.length >= 8 ? args[7] : ''

def dateFormat = new SimpleDateFormat('dd/MM/yyyy')
dateFormat.setLenient(false)
def isoDateFormat = new SimpleDateFormat('yyyy-MM-dd')

def field = { obj, name ->
  def c = obj.getClass()
  while (c != null) {
    try {
      def f = c.getDeclaredField(name)
      f.accessible = true
      return f.get(obj)
    } catch (NoSuchFieldException ignored) {
      c = c.superclass
    }
  }
  return null
}

def readRpcArgs = { path ->
  def input = new ObjectInputStream(new FileInputStream(path))
  input.readFully(new byte[188])
  def tableauBord = input.readObject()
  try {
    input.readFully(new byte[1])
  } catch (Exception ignored) {
  }
  def stats = input.readObject()
  return [tableauBord, stats]
}

def criteriaValue = { value ->
  if (value == null) {
    return ''
  }
  def parts = []
  ['getKey', 'getCode', 'getLabel'].each { methodName ->
    try {
      def item = value."$methodName"()
      if (item != null) {
        parts << String.valueOf(item).trim()
      }
    } catch (Throwable ignored) {
    }
  }
  return parts.findAll { it }.unique().join(' | ')
}

def walkRows
walkRows = { node, meta, prefix, rows ->
  def current = new LinkedHashMap(prefix)
  def displayValues = node.getDisplayCriteriaValues() ?: []
  def displayCriterias = meta.getDisplayCriterias() ?: []
  for (int i = 0; i < displayValues.length; i++) {
    def value = criteriaValue(displayValues[i])
    if (value) {
      current[i < displayCriterias.length ? displayCriterias[i].getName() : "display_${i}"] = value
    }
  }
  def hiddenValues = node.getHiddenCriteriaValues() ?: []
  def hiddenCriterias = meta.getHiddenCriterias() ?: []
  for (int i = 0; i < hiddenValues.length; i++) {
    def value = criteriaValue(hiddenValues[i])
    if (value) {
      current["hidden." + (i < hiddenCriterias.length ? hiddenCriterias[i].getName() : "hidden_${i}")] = value
    }
  }
  def values = node.getValues()
  if (values && values.length) {
    def columns = meta.getColumns() ?: []
    for (int i = 0; i < values.length; i++) {
      if (values[i] != null) {
        current[i < columns.length ? columns[i].getLabel() : "col_${i}"] = String.valueOf(values[i])
      }
    }
  }

  def children = node.getChildren() ?: []
  if (!children.length && current) {
    rows << current
  }
  children.each { child -> walkRows(child, meta, current, rows) }
  return rows
}

def resultRows = { tbResult ->
  def result = field(tbResult, 'result')
  if (result == null) {
    return []
  }
  return walkRows(result.getRootNode(), result.getMetadata(), new LinkedHashMap(), [])
}

def splitValue = { value ->
  String.valueOf(value ?: '').split(/\s*\|\s*/).collect { it.trim() }.findAll { it }
}

def codePart = { value ->
  def parts = splitValue(value)
  return parts ? parts[0] : ''
}

def secondPart = { value ->
  def parts = splitValue(value)
  return parts.size() >= 2 ? parts[1] : (parts ? parts[0] : '')
}

def thirdPart = { value ->
  def parts = splitValue(value)
  return parts.size() >= 3 ? parts[2] : (parts ? parts[-1] : '')
}

def csvEscape = { value ->
  def text = String.valueOf(value == null ? '' : value)
  if (text.contains('"') || text.contains(';') || text.contains('\n') || text.contains('\r')) {
    return '"' + text.replace('"', '""') + '"'
  }
  return text
}

def safeCall = { obj, methodName ->
  try {
    return obj?."$methodName"()
  } catch (Throwable ignored) {
    return null
  }
}

def buildLineExtractor = { path, moduleName, sourceName ->
  if (!path) {
    return null
  }
  def template = new File(path)
  if (!template.exists()) {
    return null
  }
  def (tableauBord, argStats) = readRpcArgs(template.absolutePath)
  def stat = (argStats ?: []).find { field(it, 'module') == moduleName }
  if (stat == null) {
    stat = field(tableauBord, 'stat').find { field(it, 'module') == moduleName }
  }
  if (stat == null) {
    return null
  }
  def query = field(stat, 'extensionMap').get(
    'fr.infologic.infoc.services.infocentre.tableaubord.InfocentreTableauBordService.queryRequest'
  )
  if (query == null) {
    return null
  }
  return [
    tableauBord: tableauBord,
    stat: stat,
    query: query,
    originalFilters: query.getFilters(),
    source: sourceName,
  ]
}

def injectCookie = { factory ->
  def httpClientField = factory.getClass().getDeclaredField('httpClient')
  httpClientField.accessible = true
  def httpClient = httpClientField.get(factory)
  def cookieManagerField = httpClient.getClass().getDeclaredField('cookieManager')
  cookieManagerField.accessible = true
  def cookieManager = cookieManagerField.get(httpClient)
  def httpCookie = new java.net.HttpCookie('JSESSIONID', cookie.replace('JSESSIONID=', ''))
  httpCookie.path = '/ventes'
  cookieManager.cookieStore.add(new URI('http://172.16.213.101:8080/ventes'), httpCookie)
}

def factory = new RemoteServiceFactoryImpl()
factory.setUrl(new URL('http://172.16.213.101:8080/ventes/ProxyServlet'))
factory.setCompression(1)
factory.setThreadRequestProperty('X-Prop-LongServiceCall', '1')
factory.setThreadRequestProperty('X-Prop-SaisieId', '')
factory.initialize()

try {
  injectCookie(factory)
  def tableauService = (InfocentreTableauBordService) factory.getService(InfocentreTableauBordService.ROLE)
  def commandeService = (CommandeService) factory.getService(CommandeService.ROLE)

  def (headerTableauBord, ignoredHeaderStats) = readRpcArgs(headerTemplatePath)
  def headerStat = field(headerTableauBord, 'stat').find { field(it, 'module') == 'vtStatCdeEntete' }
  def headerQuery = field(headerStat, 'extensionMap').get(
    'fr.infologic.infoc.services.infocentre.tableaubord.InfocentreTableauBordService.queryRequest'
  )

  def lineExtractors = [
    buildLineExtractor(lineTemplatePath, 'vtCdeLigNonPeriodique', 'non_periodic'),
    buildLineExtractor(periodicLineTemplatePath, 'vtCdeLigLivAPeriodique', 'periodic'),
  ].findAll { it != null }
  if (!lineExtractors) {
    throw new IllegalArgumentException('Aucun template de lignes Copilote exploitable.')
  }

  def outRows = []
  def seenOrders = new LinkedHashSet()
  def fromDate = dateFormat.parse(dateFromText)
  def toDate = dateFormat.parse(dateToText)
  def calendar = Calendar.getInstance()
  calendar.setTime(fromDate)

  while (!calendar.getTime().after(toDate)) {
    def searchDate = calendar.getTime()
    factory.setThreadRequestProperty('X-Prop-ServiceSource', 'EMALO replay extract vtrcom headers')
    headerQuery.setFilters([new InFilter('datDepart', [searchDate])] as IFilter[])
    def headerResults = tableauService.execute2(
      headerTableauBord,
      [headerStat] as TableauBordStat[]
    )
    def headerRows = []
    headerResults.each { headerRows.addAll(resultRows(it)) }

    headerRows.each { header ->
      def orderNumber = secondPart(header['hidden.N° cde'] ?: header['hidden.Commande'])
      def operatorCode = codePart(header['Opér'])
      if (!orderNumber) {
        return
      }
      if (operatorFilter != 'ALL' && operatorCode.toUpperCase() != operatorFilter) {
        return
      }
      if (!seenOrders.add(orderNumber)) {
        return
      }

      try {
        factory.setThreadRequestProperty('X-Prop-ServiceSource', 'EMALO replay load order')
        def dto = commandeService.loadNumCde(orderNumber, true)
        def cde = safeCall(dto, 'getCommande')
        def commandIk = String.valueOf(safeCall(cde, 'getIk') ?: '')

        def lineRows = []
        for (extractor in lineExtractors) {
          factory.setThreadRequestProperty('X-Prop-ServiceSource', "EMALO replay extract order lines ${extractor.source}")
          def filters = [new InFilter('cde', [new IK(Long.parseLong(commandIk))])]
          def originalFilters = extractor.originalFilters ?: []
          for (int filterIndex = 1; filterIndex < originalFilters.length; filterIndex++) {
            if (originalFilters[filterIndex] != null) {
              filters << originalFilters[filterIndex]
            }
          }
          extractor.query.setFilters(filters as IFilter[])
          def lineResults = tableauService.execute2(
            extractor.tableauBord,
            [extractor.stat] as TableauBordStat[]
          )
          def extractedRows = []
          lineResults.each { tb ->
            resultRows(tb).each { row ->
              row['__line_source'] = extractor.source
              extractedRows << row
            }
          }
          if (extractedRows) {
            lineRows.addAll(extractedRows)
            break
          }
        }

        if (!lineRows) {
          outRows << [
            search_date: isoDateFormat.format(searchDate),
            order_number: orderNumber,
            command_ik: commandIk,
            operator: operatorCode,
            client_code: secondPart(header['Client livré']),
            client_label: thirdPart(header['Client livré']),
            order_date: safeCall(cde, 'getDatCde'),
            departure_date: safeCall(cde, 'getDatDepart'),
            delivery_date: safeCall(cde, 'getDatLiv'),
            article_code: '',
            designation: '',
            quantity: '',
            unit: '',
            quantity_billed: '',
            unit_billed: '',
            source: 'copilote_replay',
            error: 'no_lines_returned',
          ]
        }

        lineRows.each { line ->
          outRows << [
            search_date: isoDateFormat.format(searchDate),
            order_number: orderNumber,
            command_ik: commandIk,
            operator: operatorCode,
            client_code: secondPart(header['Client livré']),
            client_label: thirdPart(header['Client livré']),
            order_date: safeCall(cde, 'getDatCde'),
            departure_date: safeCall(cde, 'getDatDepart'),
            delivery_date: safeCall(cde, 'getDatLiv'),
            article_code: line['Article'] ?: '',
            designation: line['Designation'] ?: '',
            quantity: line['Qté cdée'] ?: '',
            unit: line['U Cde'] ?: '',
            quantity_billed: line['Q Cde UF'] ?: '',
            unit_billed: line['U Fac'] ?: '',
            source: "copilote_replay:${line['__line_source'] ?: 'unknown'}",
            error: '',
          ]
        }
      } catch (Throwable orderError) {
        outRows << [
          search_date: isoDateFormat.format(searchDate),
          order_number: orderNumber,
          command_ik: '',
          operator: operatorCode,
          client_code: secondPart(header['Client livré']),
          client_label: thirdPart(header['Client livré']),
          order_date: header['Date cde'] ?: '',
          departure_date: header['Date départ'] ?: '',
          delivery_date: '',
          article_code: '',
          designation: '',
          quantity: '',
          unit: '',
          quantity_billed: '',
          unit_billed: '',
          source: 'copilote_replay',
          error: orderError.getClass().getSimpleName() + ': ' + String.valueOf(orderError.getMessage()),
        ]
      }
    }

    calendar.add(Calendar.DATE, 1)
  }

  outputCsv.parentFile?.mkdirs()
  def columns = [
    'search_date',
    'order_number',
    'command_ik',
    'operator',
    'client_code',
    'client_label',
    'order_date',
    'departure_date',
    'delivery_date',
    'article_code',
    'designation',
    'quantity',
    'unit',
    'quantity_billed',
    'unit_billed',
    'source',
    'error',
  ]
  outputCsv.withWriter('UTF-8') { writer ->
    writer.println(columns.join(';'))
    outRows.each { row ->
      writer.println(columns.collect { csvEscape(row[it]) }.join(';'))
    }
  }
  println("OUTPUT=${outputCsv.absolutePath}")
  println("ORDERS=${seenOrders.size()}")
  println("LINES=${outRows.size()}")
} finally {
  factory.dispose()
}
