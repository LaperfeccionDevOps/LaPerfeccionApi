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
 *   3. (Opcional) Ejecutar probarEscritura() para ver una pestaña de ejemplo.
 *   4. Implementar > Nueva implementación > Aplicación web:
 *        Ejecutar como: Yo · Quién tiene acceso: Cualquier usuario.
 *      La URL que termina en /exec va en CONTABILIDAD_APPSCRIPT_URL.
 *   Al cambiar el código: Implementar > Gestionar implementaciones > editar >
 *   Versión nueva (así la URL no cambia).
 *
 * Contrato del POST (JSON):
 *   {
 *     "clave": "...",
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
const MAX_REGISTRO = 500;
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
  return responder({ ok: true, servicio: 'contabilidad-centros-costo', version: 1 });
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
    return responder({ ok: true, hojas: procesar(datos) });
  } catch (error) {
    return responder({ ok: false, error: String((error && error.message) || error) });
  } finally {
    candado.releaseLock();
  }
}

// Ejecutar a mano desde el editor para ver cómo queda una pestaña.
function probarEscritura() {
  procesar({
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
  });
}

// ─── Proceso ───

function procesar(datos) {
  validarPaquete(datos);

  const libro = obtenerLibro();
  const resumen = datos.hojas.map((h, i) => {
    const hoja = escribirHoja(libro, h);
    libro.setActiveSheet(hoja);
    libro.moveActiveSheet(i + 1);
    return { nombre: h.nombre, filas: h.filas.length };
  });

  quitarHojaInicialVacia(libro, datos.hojas.map((h) => h.nombre));
  registrar(libro, datos, resumen);
  SpreadsheetApp.flush();
  return resumen;
}

function obtenerLibro() {
  const libro = SpreadsheetApp.getActiveSpreadsheet();
  if (!libro) {
    throw new Error('El script debe crearse desde la hoja (Extensiones > Apps Script).');
  }
  return libro;
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

function escribirHoja(libro, h) {
  const hoja = libro.getSheetByName(h.nombre) || libro.insertSheet(h.nombre);
  const columnas = h.encabezados.length;
  const tipos = h.tipos || h.encabezados.map(() => 'texto');
  const total = h.filas.length + 1;

  const filtro = hoja.getFilter();
  if (filtro) {
    filtro.remove();
  }
  hoja.clear();
  ajustarTamano(hoja, total, columnas);

  // El formato va antes de los valores: así "01" o un NIT no se vuelven número.
  tipos.forEach((t, i) => hoja.getRange(2, i + 1, Math.max(total - 1, 1), 1).setNumberFormat(FORMATOS[t]));
  hoja.getRange(1, 1, 1, columnas).setNumberFormat('@');

  const valores = [h.encabezados.map(String)].concat(
    h.filas.map((fila) => fila.map((valor, i) => convertir(valor, tipos[i])))
  );
  hoja.getRange(1, 1, total, columnas).setValues(valores);

  hoja
    .getRange(1, 1, 1, columnas)
    .setFontWeight('bold')
    .setFontColor('#ffffff')
    .setBackground(COLOR_ENCABEZADO)
    .setWrap(true)
    .setVerticalAlignment('middle');
  hoja.setFrozenRows(1);
  hoja.getRange(1, 1, total, columnas).createFilter();
  hoja.autoResizeColumns(1, columnas);

  proteger(hoja);
  return hoja;
}

// Deja exactamente las filas y columnas necesarias (al menos una fila libre,
// porque Sheets no permite borrar todas las filas no inmovilizadas).
function ajustarTamano(hoja, filas, columnas) {
  hoja.setFrozenRows(0);
  const filasDeseadas = filas + 1;

  const maxFilas = hoja.getMaxRows();
  if (maxFilas < filasDeseadas) {
    hoja.insertRowsAfter(maxFilas, filasDeseadas - maxFilas);
  } else if (maxFilas > filasDeseadas) {
    hoja.deleteRows(filasDeseadas + 1, maxFilas - filasDeseadas);
  }

  const maxColumnas = hoja.getMaxColumns();
  if (maxColumnas < columnas) {
    hoja.insertColumnsAfter(maxColumnas, columnas - maxColumnas);
  } else if (maxColumnas > columnas) {
    hoja.deleteColumns(columnas + 1, maxColumnas - columnas);
  }
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

// La hoja nueva trae "Hoja 1"; se quita si quedó vacía y no se usa.
function quitarHojaInicialVacia(libro, usadas) {
  ['Hoja 1', 'Hoja1', 'Sheet1'].forEach((nombre) => {
    const hoja = libro.getSheetByName(nombre);
    if (hoja && usadas.indexOf(nombre) === -1 && hoja.getLastRow() === 0 && libro.getSheets().length > 1) {
      libro.deleteSheet(hoja);
    }
  });
}

function registrar(libro, datos, resumen) {
  let hoja = libro.getSheetByName(HOJA_REGISTRO);
  if (!hoja) {
    hoja = libro.insertSheet(HOJA_REGISTRO);
    hoja.appendRow(['Fecha', 'Origen', 'Usuario', 'Evento', 'Hojas', 'Filas']);
    hoja.getRange(1, 1, 1, 6).setFontWeight('bold').setFontColor('#ffffff').setBackground(COLOR_ENCABEZADO);
    hoja.setFrozenRows(1);
    hoja.getRange('A:A').setNumberFormat('dd/mm/yyyy hh:mm:ss');
    proteger(hoja);
  }

  hoja.insertRowAfter(1);
  hoja
    .getRange(2, 1, 1, 6)
    .setValues([
      [
        new Date(),
        convertir(datos.origen || '', 'texto'),
        convertir(datos.usuario || '', 'texto'),
        convertir(datos.evento || '', 'texto'),
        resumen.map((r) => r.nombre).join(', '),
        resumen.reduce((suma, r) => suma + r.filas, 0),
      ],
    ])
    // La fila insertada hereda el estilo del encabezado; se limpia.
    .setFontWeight('normal')
    .setFontColor('#000000')
    .setBackground(null);

  // El más reciente arriba; se conservan los últimos MAX_REGISTRO.
  const sobrantes = hoja.getLastRow() - 1 - MAX_REGISTRO;
  if (sobrantes > 0) {
    hoja.deleteRows(MAX_REGISTRO + 2, sobrantes);
  }
  libro.setActiveSheet(hoja);
  libro.moveActiveSheet(libro.getSheets().length);
}

function responder(objeto) {
  return ContentService.createTextOutput(JSON.stringify(objeto)).setMimeType(ContentService.MimeType.JSON);
}
