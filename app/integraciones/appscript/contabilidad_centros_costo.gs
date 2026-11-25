/**
 * La Perfección · Contabilidad — espejo de Centros de Costo en Google Sheets.
 *
 * La API del portal envía aquí (POST) la foto completa de los centros de costo
 * cada vez que Contabilidad guarda un cambio, y una vez al día en un refresco
 * programado. Este script reemplaza cada pestaña recibida; la hoja es solo de
 * consulta (las pestañas quedan con protección de advertencia).
 *
 * Instalación:
 *   1. Crear la hoja de Google > Extensiones > Apps Script > pegar este código.
 *   2. Configuración del proyecto (engranaje):
 *        - Zona horaria: (GMT-05:00) Bogotá.
 *        - Propiedades de la secuencia de comandos: agregar CLAVE con una clave
 *          larga (la misma de CONTABILIDAD_APPSCRIPT_CLAVE en el .env de la API).
 *   3. Habilitar el servicio avanzado Sheets API. Configurar AMBIENTE, BASE,
 *      DESTINO_ID y ESPEJO_DEDICADO=SI. Solo un espejo dedicado, nunca el Excel oficial.
 *      probarEscritura() solo se permite en QA y en una pestaña Prueba separada.
 *   4. Implementar > Nueva implementación > Aplicación web:
 *        Ejecutar como: Yo · Quién tiene acceso: Cualquier usuario.
 *      La URL que termina en /exec va en CONTABILIDAD_APPSCRIPT_URL.
 *   Al cambiar el código: Implementar > Gestionar implementaciones > editar >
 *   Versión nueva (así la URL no cambia).
 *
 * Contrato del POST (JSON):
 *   {
 *     "clave": "...",
 *     "ambiente": "QA" | "PRODUCCION",
 *     "base": "...",
 *     "destino_id": "...",
 *     "origen": "cambio" | "programado" | "manual",
 *     "usuario": "NOMBRE.USUARIO",
 *     "evento": "Cierre del centro ...",
 *     "hojas": [
 *       {
 *         "nombre": "Centros de costo",
 *         "encabezados": ["Código", "Apertura", "Horas semana", ...],
 *         "tipos": ["texto", "fecha", "decimal", ...],
 *         "filas": [["01-...", "2026-11-11", 42], ...]
 *       }
 *     ]
 *   }
 * Tipos: texto, entero, decimal, fecha (YYYY-MM-DD), fecha_hora (YYYY-MM-DDTHH:MM[:SS]).
 * Respuesta: { "ok": true, "hojas": [{ "nombre", "filas" }] } o { "ok": false, "error" }.
 */

const PROPIEDAD_CLAVE = 'CLAVE';
const HOJA_REGISTRO = 'Registro de envíos';
// El registro conserva todos los envíos; no se recorta.
const HOJAS_AUTORIZADAS = ['Resumen', 'Centros de costo', 'Asignaciones vigentes', 'CC'];
const MAX_HOJAS = 10;

const FORMATOS = {
  texto: '@',
  entero: '#,##0',
  decimal: '#,##0.00',
  fecha: 'dd/mm/yyyy',
  fecha_hora: 'dd/mm/yyyy hh:mm',
};

const COLOR_ENCABEZADO = '#065f46';

// ─── Puntos de entrada ───

function doGet() {
  // Solo confirma que la URL responde; no expone datos.
  return responder({ ok: true, servicio: 'contabilidad-centros-costo', version: 2 });
}

function doPost(e) {
  let datos;
  try {
    datos = JSON.parse(e.postData.contents);
  } catch (error) {
    return responder({ ok: false, error: 'El cuerpo no es JSON válido.' });
  }

  const errorClave = validarClave(datos && datos.clave);
  if (errorClave) {
    return responder({ ok: false, error: errorClave });
  }

  // Un envío a la vez: si llegan dos cambios seguidos, el segundo espera.
  const candado = LockService.getScriptLock();
  if (!candado.tryLock(30000)) {
    return responder({ ok: false, error: 'Otra actualización está en curso; reintenta.' });
  }

  try {
    return responder({ ok: true, hojas: procesar(datos), ambiente: datos.ambiente, destino_id: datos.destino_id });
  } catch (error) {
    return responder({ ok: false, error: String((error && error.message) || error) });
  } finally {
    candado.releaseLock();
  }
}

// Ejecutar a mano desde el editor para ver cómo queda una pestaña.
function probarEscritura() {
  const p = PropertiesService.getScriptProperties();
  if (p.getProperty('AMBIENTE') !== 'QA') throw new Error('Prueba permitida solo en QA.');
  const candado = LockService.getScriptLock();
  if (!candado.tryLock(30000)) throw new Error('Actualización en curso.');
  try {
  procesar({
    ambiente: 'QA', base: p.getProperty('BASE'), destino_id: p.getProperty('DESTINO_ID'),
    origen: 'manual',
    usuario: Session.getActiveUser().getEmail() || 'editor',
    evento: 'Prueba desde el editor',
    hojas: [
      {
        nombre: 'Prueba',
        encabezados: ['Código', 'Cliente', 'Estado', 'Apertura', 'Operarios', 'Horas nocturnas', 'Actualizado'],
        tipos: ['texto', 'texto', 'texto', 'fecha', 'entero', 'decimal', 'fecha_hora'],
        filas: [
          ['01-0001-COMPE22-11ASALT-0802LIVI', 'CLIENTE DE PRUEBA', 'ABIERTO', '2026-11-11', 3, 12.5, '2026-11-11T08:30'],
          ['01-0002-ZZPRUEBA-11ASALT-0802LIVI', 'OTRO CLIENTE', 'CERRADO', '2026-10-01', 0, 0, '2026-11-11T08:31'],
        ],
      },
    ],
  }, true);
  } finally { candado.releaseLock(); }
}

// ─── Proceso ───

function procesar(datos, prueba = false) {
  validarPaquete(datos);
  const libro = obtenerLibro(datos);
  const permitidas = prueba ? ['Prueba'] : HOJAS_AUTORIZADAS;
  if (datos.hojas.length !== permitidas.length || !permitidas.every(n => datos.hojas.some(h => h.nombre === n))) {
    throw new Error('Conjunto de pestañas no autorizado.');
  }
  if (!prueba && datos.hojas.some(h => ['CC', 'Centros de costo'].includes(h.nombre) && !h.filas.length)) {
    throw new Error('Exportación de centros vacía; no se escribe.');
  }
  const solicitudes = [];
  const resumen = datos.hojas.map(h => {
    escribirHoja(libro, h, solicitudes);
    return { nombre: h.nombre, filas: h.filas.length };
  });
  registrar(libro, datos, resumen, solicitudes);
  // Todas las validaciones preceden a la única escritura atómica.
  Sheets.Spreadsheets.batchUpdate({ requests: solicitudes }, libro.getId());
  return resumen;
}

function obtenerLibro(datos) {
  const p = PropertiesService.getScriptProperties();
  const ambiente = p.getProperty('AMBIENTE');
  const base = p.getProperty('BASE');
  const destino = p.getProperty('DESTINO_ID');
  if (!['QA', 'PRODUCCION'].includes(ambiente) || !base || !destino ||
      p.getProperty('ESPEJO_DEDICADO') !== 'SI' || datos.ambiente !== ambiente ||
      datos.base !== base || datos.destino_id !== destino ||
      ((ambiente === 'QA') !== (base === 'LA_PERFECCION_QA'))) {
    throw new Error('Ambiente, base o destino no autorizado.');
  }
  return SpreadsheetApp.openById(destino);
}

function validarClave(clave) {
  const esperada = PropertiesService.getScriptProperties().getProperty(PROPIEDAD_CLAVE);
  if (!esperada) {
    return 'Falta configurar la propiedad CLAVE del script.';
  }
  if (typeof clave !== 'string' || !igualesSeguro(clave, esperada)) {
    return 'Clave inválida.';
  }
  return null;
}

// Comparación de tiempo constante para no filtrar la clave por tiempos.
function igualesSeguro(a, b) {
  const da = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, a, Utilities.Charset.UTF_8);
  const db = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, b, Utilities.Charset.UTF_8);
  let diferencia = 0;
  for (let i = 0; i < da.length; i++) {
    diferencia |= da[i] ^ db[i];
  }
  return diferencia === 0;
}

function validarPaquete(datos) {
  if (!datos || !Array.isArray(datos.hojas) || datos.hojas.length === 0) {
    throw new Error('El paquete no trae hojas.');
  }
  if (datos.hojas.length > MAX_HOJAS) {
    throw new Error('Máximo ' + MAX_HOJAS + ' hojas por envío.');
  }

  const nombres = {};
  datos.hojas.forEach((h) => {
    if (!h || typeof h.nombre !== 'string' || !h.nombre.trim() || h.nombre.length > 90) {
      throw new Error('Cada hoja necesita un nombre (máximo 90 caracteres).');
    }
    if (h.nombre === HOJA_REGISTRO) {
      throw new Error('"' + HOJA_REGISTRO + '" es una hoja reservada.');
    }
    if (nombres[h.nombre]) {
      throw new Error('Hoja repetida: ' + h.nombre);
    }
    nombres[h.nombre] = true;

    if (!Array.isArray(h.encabezados) || h.encabezados.length === 0) {
      throw new Error('La hoja "' + h.nombre + '" no trae encabezados.');
    }
    const columnas = h.encabezados.length;
    if (h.tipos && (!Array.isArray(h.tipos) || h.tipos.length !== columnas)) {
      throw new Error('La hoja "' + h.nombre + '" trae tipos que no coinciden con los encabezados.');
    }
    (h.tipos || []).forEach((t) => {
      if (!FORMATOS[t]) {
        throw new Error('Tipo desconocido en "' + h.nombre + '": ' + t);
      }
    });
    if (!Array.isArray(h.filas)) {
      throw new Error('La hoja "' + h.nombre + '" no trae filas.');
    }
    h.filas.forEach((f, i) => {
      if (!Array.isArray(f) || f.length !== columnas) {
        throw new Error('Fila ' + (i + 1) + ' de "' + h.nombre + '" no tiene ' + columnas + ' columnas.');
      }
    });
  });
}

function escribirHoja(libro, h, solicitudes) {
  const hoja = libro.getSheetByName(h.nombre);
  if (!hoja) throw new Error('Falta pestaña autorizada: ' + h.nombre);
  const columnas = h.encabezados.length;
  const tipos = h.tipos || h.encabezados.map(() => 'texto');
  const total = h.filas.length + 1;
  const anterior = hoja.getLastRow();
  const alto = Math.max(total, anterior);
  if (hoja.getLastColumn() > columnas) throw new Error('Columnas adicionales: ' + h.nombre);
  if (anterior) {
    if (hoja.getMaxColumns() < columnas) throw new Error('Esquema insuficiente: ' + h.nombre);
    const actual = hoja.getRange(1, 1, 1, columnas).getDisplayValues()[0];
    if (actual.some((v, i) => v !== String(h.encabezados[i]))) throw new Error('Encabezados diferentes: ' + h.nombre);
    const rango = hoja.getRange(1, 1, anterior, columnas);
    if (rango.getFormulas().some(r => r.some(Boolean)) || rango.getNotes().some(r => r.some(Boolean))) {
      throw new Error('Fórmulas o notas existentes: ' + h.nombre);
    }
  }
  ajustarTamano(hoja, alto, columnas, solicitudes);
  const id = hoja.getSheetId();
  const valores = [h.encabezados.map(v => celda(v, 'texto'))].concat(
    h.filas.map(fila => fila.map((valor, i) => celda(valor, tipos[i])))
  );
  // Solo valores del espejo: conserva formatos, pestañas y dimensiones.
  // Las filas sobrantes del snapshot se vacían dentro del rango automático.
  solicitudes.push({ updateCells: {
    range: { sheetId: id, startRowIndex: 0, endRowIndex: alto, startColumnIndex: 0, endColumnIndex: columnas },
    rows: valores.map(values => ({ values })), fields: 'userEnteredValue'
  }});
  // Formatos originales para columnas automáticas; no se toca el resto.
  tipos.forEach((t, i) => {
    if (total > 1) solicitudes.push({ repeatCell: {
      range: { sheetId: id, startRowIndex: 1, endRowIndex: total, startColumnIndex: i, endColumnIndex: i + 1 },
      cell: { userEnteredFormat: { numberFormat: { type: t === 'texto' ? 'TEXT' : t === 'fecha' ? 'DATE' : t === 'fecha_hora' ? 'DATE_TIME' : 'NUMBER', pattern: FORMATOS[t] } } },
      fields: 'userEnteredFormat.numberFormat'
    }});
  });
  // No modificar filtros existentes ni sus criterios.
  return hoja;
}

// Solo ampliar dimensiones; nunca eliminar filas ni columnas.
function ajustarTamano(hoja, filas, columnas, solicitudes) {
  const id = hoja.getSheetId();
  if (hoja.getMaxRows() < filas) solicitudes.push({ appendDimension: { sheetId: id, dimension: 'ROWS', length: filas - hoja.getMaxRows() } });
  if (hoja.getMaxColumns() < columnas) solicitudes.push({ appendDimension: { sheetId: id, dimension: 'COLUMNS', length: columnas - hoja.getMaxColumns() } });
}

// Valores tipados para Sheets API: el texto nunca se interpreta como fórmula.
function celda(valor, tipo) {
  if (valor === null || valor === undefined || valor === '') return {};
  if (tipo === 'entero' || tipo === 'decimal') {
    const n = Number(valor);
    if (!Number.isFinite(n)) throw new Error('Número inválido.');
    return { userEnteredValue: { numberValue: n } };
  }
  if (tipo === 'fecha' || tipo === 'fecha_hora') {
    const fecha = aFecha(String(valor));
    if (!fecha) throw new Error('Fecha inválida.');
    const serial = Date.UTC(fecha.getFullYear(), fecha.getMonth(), fecha.getDate(), fecha.getHours(), fecha.getMinutes(), fecha.getSeconds()) / 86400000 + 25569;
    return { userEnteredValue: { numberValue: serial } };
  }
  return { userEnteredValue: { stringValue: String(valor) } };
}

function convertir(valor, tipo) {
  if (valor === null || valor === undefined || valor === '') {
    return '';
  }
  switch (tipo) {
    case 'entero':
    case 'decimal': {
      const numero = Number(valor);
      return isNaN(numero) ? String(valor) : numero;
    }
    case 'fecha':
    case 'fecha_hora': {
      const fecha = aFecha(String(valor));
      return fecha || String(valor);
    }
    default: {
      const texto = String(valor);
      // Un texto que empieza con "=" se escribiría como fórmula.
      return texto.charAt(0) === '=' ? "'" + texto : texto;
    }
  }
}

// "2026-11-11" o "2026-11-11T08:30[:00]" → Date en la zona horaria del script.
function aFecha(texto) {
  const m = texto.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/);
  if (!m) {
    return null;
  }
  return new Date(
    Number(m[1]),
    Number(m[2]) - 1,
    Number(m[3]),
    Number(m[4] || 0),
    Number(m[5] || 0),
    Number(m[6] || 0)
  );
}

// Protección de solo advertencia: quien edite ve el aviso de que la pestaña
// se reemplaza en la próxima actualización.
function proteger(hoja) {
  if (hoja.getProtections(SpreadsheetApp.ProtectionType.SHEET).length === 0) {
    hoja
      .protect()
      .setDescription('Espejo del portal: se reemplaza en cada actualización.')
      .setWarningOnly(true);
  }
}

// No eliminar hojas iniciales: pueden contener formatos o conexiones.
function quitarHojaInicialVacia(libro, usadas) {
  return;
}

function registrar(libro, datos, resumen, solicitudes) {
  const hoja = libro.getSheetByName(HOJA_REGISTRO);
  if (!hoja) throw new Error('Falta Registro de envíos.');
  const encabezados = ['Fecha', 'Origen', 'Usuario', 'Evento', 'Hojas', 'Filas'];
  if (hoja.getRange(1, 1, 1, 6).getDisplayValues()[0].some((v, i) => v !== encabezados[i])) {
    throw new Error('Encabezados del registro diferentes.');
  }
  // Mantener el orden original: más reciente arriba, sin recortar el historial.
  const id = hoja.getSheetId();
  solicitudes.push({ insertDimension: { range: { sheetId: id, dimension: 'ROWS', startIndex: 1, endIndex: 2 }, inheritFromBefore: false } });
  const fecha = Utilities.formatDate(new Date(), 'America/Bogota', "yyyy-MM-dd'T'HH:mm:ss");
  const valores = [fecha, datos.origen || '', datos.usuario || '', datos.evento || '',
    resumen.map(r => r.nombre).join(', '), resumen.reduce((suma, r) => suma + r.filas, 0)];
  solicitudes.push({ updateCells: { start: { sheetId: id, rowIndex: 1, columnIndex: 0 },
    rows: [{ values: valores.map((v, i) => celda(v, i === 0 ? 'fecha_hora' : i === 5 ? 'entero' : 'texto')) }], fields: 'userEnteredValue' } });
  solicitudes.push({ repeatCell: { range: { sheetId: id, startRowIndex: 1, endRowIndex: 2, startColumnIndex: 0, endColumnIndex: 6 },
    cell: { userEnteredFormat: { textFormat: { bold: false }, backgroundColor: { red: 1, green: 1, blue: 1 } } },
    fields: 'userEnteredFormat.textFormat.bold,userEnteredFormat.backgroundColor' } });
}

function responder(objeto) {
  return ContentService.createTextOutput(JSON.stringify(objeto)).setMimeType(ContentService.MimeType.JSON);
}
