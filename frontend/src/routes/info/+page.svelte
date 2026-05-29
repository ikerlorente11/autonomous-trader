<script lang="ts">
	import Card from '$lib/components/Card.svelte';

	// Página estática (sin llamadas a la API). Describe lo que el sistema hace HOY,
	// no el objetivo a futuro: análisis solo técnico, paper trading, sin dinero real.
	const flow = [
		{ step: '1', title: 'Datos', text: 'Precios diarios (OHLCV) de yfinance' },
		{ step: '2', title: 'Indicadores', text: 'RSI · Tendencia · Volatilidad' },
		{ step: '3', title: 'Score', text: 'Puntuación compuesta 0–100' },
		{ step: '4', title: 'Ranking', text: 'Mejores candidatos de compra' },
		{ step: '5', title: 'Tamaño', text: 'Según el presupuesto de la cartera' },
		{ step: '6', title: 'Órdenes', text: 'Compra simulada (paper)' },
		{ step: '7', title: 'NAV', text: 'Foto del valor de la cartera' }
	];
</script>

<h1 class="page-title">Cómo funciona</h1>

<Card span="full">
	<p class="lead">
		Soy un sistema autónomo de <strong>paper trading</strong>: analizo el mercado cada día,
		simulo inversiones en carteras virtuales y muestro el resultado en este panel.
		<strong>No se mueve dinero real</strong> — es una simulación para probar la estrategia.
	</p>
</Card>

<Card title="El recorrido de un día" caption="De los datos a la inversión, paso a paso" span="full">
	<div class="flow">
		{#each flow as f, i (f.step)}
			<div class="node">
				<span class="num">{f.step}</span>
				<span class="node-title">{f.title}</span>
				<span class="node-text">{f.text}</span>
			</div>
			{#if i < flow.length - 1}<span class="arrow" aria-hidden="true">→</span>{/if}
		{/each}
	</div>
</Card>

<Card title="1 · De dónde saco la información" span="full">
	<ul class="list">
		<li><strong>Precios de mercado (OHLCV diario):</strong> apertura, máximo, mínimo, cierre y volumen, vía <code>yfinance</code> (gratis, sin clave). Si falla, hay un proveedor de respaldo (<code>Twelve Data</code>).</li>
		<li><strong>Qué activos miro:</strong> solo los símbolos de tu <strong>watchlist</strong>, que defines tú en la página <a href="/market">Market</a>. Sin símbolos, no hago nada.</li>
		<li><strong>Frecuencia:</strong> una vela por día y por símbolo. No opero intradía.</li>
	</ul>
	<p class="note">
		Hoy trabajo <strong>solo con el precio</strong>. Las señales de fundamentales, macro, noticias
		y sentimiento están previstas en el diseño pero <strong>aún no están activas</strong>.
	</p>
</Card>

<Card title="2 · Cómo uso esa información (análisis)" span="full">
	<p>Para cada símbolo calculo tres <strong>indicadores técnicos</strong>, cada uno con una sub-puntuación de 0 a 100:</p>
	<ul class="list">
		<li><strong>Momento (RSI, 14 días):</strong> si el valor viene subiendo con fuerza o está agotado.</li>
		<li><strong>Tendencia (media móvil EMA, 20 días):</strong> cuánto se separa el precio de su media — arriba es alcista.</li>
		<li><strong>Volatilidad (ATR, 14 días):</strong> cuánto se mueve el precio, como medida de riesgo.</li>
	</ul>
	<p>
		Combino las tres en una <strong>puntuación compuesta 0–100</strong> con pesos configurables
		(por defecto: RSI 50 %, tendencia 30 %, volatilidad 20 %). Si falta algún indicador, reparto su
		peso entre los presentes — nunca lo cuento como cero. Todos los pesos y umbrales viven en
		<code>config/strategy.yaml</code>, no en el código.
	</p>
</Card>

<Card title="3 · Cómo decido" span="full">
	<ul class="list">
		<li><strong>Ordeno</strong> los símbolos por puntuación, de mayor a menor.</li>
		<li><strong>Umbral mínimo:</strong> solo considero comprar si la puntuación llega al mínimo (por defecto 60). Por debajo, la acción es «mantener» (HOLD).</li>
		<li><strong>Calidad de datos:</strong> descarto símbolos con datos insuficientes o sospechosos.</li>
		<li><strong>Hoy solo abro compras.</strong> No genero ventas automáticas: las posiciones se mantienen y se revalorizan con el precio.</li>
	</ul>
</Card>

<Card title="4 · Cómo invierto" span="full">
	<ul class="list">
		<li><strong>Dimensionado por presupuesto:</strong> destino un % del valor de la cartera a cada posición (por defecto 5 %), con un máximo de posiciones simultáneas (10) y una <strong>reserva de caja</strong> mínima (20 %).</li>
		<li><strong>Acciones fraccionadas:</strong> puedo comprar fracciones, así un presupuesto pequeño también invierte en valores caros. Ignoro importes minúsculos (suelo configurable).</li>
		<li><strong>Ejecución simulada:</strong> el «PaperBroker» rellena las órdenes al último cierre conocido, aplicando un pequeño deslizamiento (slippage, 0,1 %) para parecerse a la realidad.</li>
		<li><strong>Listo para real:</strong> cambiar de simulación a un bróker real sería cambiar una sola variable de entorno — sin tocar la lógica.</li>
	</ul>
</Card>

<Card title="5 · Carteras y dinero" span="full">
	<ul class="list">
		<li><strong>Varias carteras</strong> con presupuestos distintos; cambias entre ellas con el selector de arriba. Cada una opera de forma independiente según su efectivo.</li>
		<li><strong>Presupuesto editable:</strong> simulas ingresos y retiradas con Deposit / Withdraw en la página <a href="/portfolios">Portfolios</a>.</li>
		<li><strong>Efectivo</strong> = depósitos − retiradas − compras + ventas.</li>
		<li><strong>Rendimiento</strong> = valor actual − capital aportado neto. Meter dinero no cuenta como ganancia.</li>
	</ul>
</Card>

<Card title="6 · Cuándo se ejecuta" span="full">
	<ul class="list">
		<li><strong>Automático cada día</strong> (horas UTC): 06:30 descargo precios → 07:30 analizo → 08:00 ejecuto operaciones → 08:15 guardo el valor de cada cartera.</li>
		<li><strong>Manual:</strong> el botón <strong>Run now</strong> del panel lanza toda la secuencia al instante. Es idempotente: repetirlo el mismo día no duplica operaciones.</li>
		<li>Solo opero en <strong>días de mercado</strong> (calendario NYSE).</li>
	</ul>
</Card>

<Card title="Límites y aviso" span="full">
	<p class="warn">
		Esto es una <strong>simulación educativa</strong>, no asesoramiento financiero. El análisis actual
		es puramente técnico y deliberadamente simple; los resultados simulados no garantizan resultados
		reales. Antes de invertir dinero real, valida la estrategia y asume tu propio criterio.
	</p>
</Card>

<style>
	.page-title {
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		margin-bottom: var(--space-5);
	}
	:global(.card) {
		margin-bottom: var(--space-4);
	}
	.lead {
		font-size: var(--text-base);
		line-height: 1.6;
		color: var(--color-text-1);
	}
	.list {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding-left: var(--space-4);
		line-height: 1.55;
		color: var(--color-text-1);
	}
	.list li {
		list-style: disc;
	}
	p {
		line-height: 1.6;
		color: var(--color-text-1);
	}
	code {
		font-family: var(--font-mono);
		font-size: 0.9em;
		background: var(--color-bg-2);
		padding: 1px 5px;
		border-radius: var(--radius-sm);
		color: var(--color-text-0);
	}
	.note {
		margin-top: var(--space-3);
		font-size: var(--text-sm);
		color: var(--color-text-2);
		border-left: 3px solid var(--color-bg-4);
		padding-left: var(--space-3);
	}
	.warn {
		font-size: var(--text-sm);
		color: var(--color-text-1);
		border-left: 3px solid var(--status-warn, var(--color-warn));
		padding-left: var(--space-3);
	}
	.flow {
		display: flex;
		flex-wrap: wrap;
		align-items: stretch;
		gap: var(--space-2);
	}
	.node {
		display: flex;
		flex-direction: column;
		gap: 2px;
		background: var(--color-bg-2);
		border: 1px solid var(--color-bg-4);
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-3);
		min-width: 120px;
	}
	.num {
		font-size: var(--text-xs);
		color: var(--color-accent, var(--color-text-2));
		font-weight: var(--weight-semibold);
	}
	.node-title {
		font-weight: var(--weight-semibold);
		color: var(--color-text-0);
		font-size: var(--text-sm);
	}
	.node-text {
		font-size: var(--text-xs);
		color: var(--color-text-2);
	}
	.arrow {
		display: flex;
		align-items: center;
		color: var(--color-text-2);
	}
	@media (max-width: 700px) {
		.arrow {
			display: none;
		}
	}
</style>
