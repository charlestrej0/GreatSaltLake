from pathlib import Path
import math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib.dates as mdates
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


ROW_NUMBER = "Row number"


def find_date_column(data):
	"""Return the first date-like column, if the CSV has one."""
	for column in data.columns:
		if "date" not in str(column).lower() and "time" not in str(column).lower():
			continue
		parsed = pd.to_datetime(data[column], errors="coerce")
		if parsed.notna().any():
			return column
	return None


def load_station_names(raw_data_dir):
	station_file = raw_data_dir / "noaa_gsl_stations.csv"
	if not station_file.is_file():
		return {}

	try:
		stations = pd.read_csv(station_file, dtype={"ID": str, "Name": str})
	except (OSError, pd.errors.ParserError, UnicodeDecodeError):
		return {}

	if not {"ID", "Name"}.issubset(stations.columns):
		return {}
	return dict(zip(stations["ID"], stations["Name"]))


def display_series_name(column, station_names):
	name = str(column)
	for station_id in sorted(station_names, key=len, reverse=True):
		if station_id and station_id in name:
			return name.replace(station_id, f"{station_names[station_id]} [{station_id}]")
	return name


class CsvGraphApp:
	def __init__(self, root):
		self.root = root
		self.root.title("Great Salt Lake CSV Graphing Tool")
		self.root.geometry("1100x720")
		self.root.minsize(760, 500)
		self.data = None
		self.csv_path = None
		self.date_column = None
		self.y_series_columns = []
		self.current_x_values = None
		self.current_x_name = None
		self.full_xlim = None
		self.full_ylim = None
		self.station_names = load_station_names(Path(__file__).resolve().parents[1] / "raw_data")

		self._build_interface()

	def _build_interface(self):
		controls = ttk.Frame(self.root, padding=12)
		controls.pack(side=tk.LEFT, fill=tk.Y)

		ttk.Button(controls, text="Choose CSV...", command=self.choose_csv).pack(fill=tk.X)
		self.file_label = ttk.Label(controls, text="No CSV selected", wraplength=220)
		self.file_label.pack(fill=tk.X, pady=(6, 16))

		ttk.Label(controls, text="X axis").pack(anchor=tk.W)
		self.x_axis = tk.StringVar(value=ROW_NUMBER)
		self.x_menu = ttk.Combobox(controls, textvariable=self.x_axis, state="readonly", width=27)
		self.x_menu.pack(fill=tk.X, pady=(3, 14))
		self.x_menu.bind("<<ComboboxSelected>>", self._on_x_axis_changed)

		ttk.Label(controls, text="Y series (select one or more)").pack(anchor=tk.W)
		list_frame = ttk.Frame(controls)
		list_frame.pack(fill=tk.BOTH, expand=True, pady=(3, 12))
		self.y_series = tk.Listbox(list_frame, selectmode=tk.EXTENDED, exportselection=False, width=30)
		self.y_series.bind("<<ListboxSelect>>", self._on_y_series_selected)
		scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.y_series.yview)
		self.y_series.configure(yscrollcommand=scrollbar.set)
		self.y_series.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
		scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

		ttk.Label(controls, text="Chart type").pack(anchor=tk.W)
		self.chart_type = tk.StringVar(value="Line")
		self.chart_menu = ttk.Combobox(
			controls,
			textvariable=self.chart_type,
			values=("Line", "Scatter", "Bar"),
			state="readonly",
		)
		self.chart_menu.pack(fill=tk.X, pady=(3, 12))
		self.chart_menu.bind("<<ComboboxSelected>>", self._on_chart_type_changed)
		ttk.Label(controls, text="X range (dates or numbers)").pack(anchor=tk.W)
		x_range_frame = ttk.Frame(controls)
		x_range_frame.pack(fill=tk.X, pady=(3, 6))
		self.range_start = tk.StringVar()
		self.range_end = tk.StringVar()
		tk.Entry(x_range_frame, textvariable=self.range_start, width=12).pack(side=tk.LEFT, fill=tk.X, expand=True)
		tk.Entry(x_range_frame, textvariable=self.range_end, width=12).pack(
			side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0)
		)
		x_range_buttons = ttk.Frame(controls)
		x_range_buttons.pack(fill=tk.X, pady=(0, 10))
		ttk.Button(x_range_buttons, text="Apply X", command=self.apply_x_range).pack(
			side=tk.LEFT, fill=tk.X, expand=True
		)
		ttk.Button(x_range_buttons, text="Reset X", command=self.reset_x_view).pack(
			side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0)
		)
		ttk.Label(controls, text="Y range (numbers)").pack(anchor=tk.W)
		y_range_frame = ttk.Frame(controls)
		y_range_frame.pack(fill=tk.X, pady=(3, 6))
		self.y_range_start = tk.StringVar()
		self.y_range_end = tk.StringVar()
		ttk.Entry(y_range_frame, textvariable=self.y_range_start, width=12).pack(
			side=tk.LEFT, fill=tk.X, expand=True
		)
		ttk.Entry(y_range_frame, textvariable=self.y_range_end, width=12).pack(
			side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0)
		)
		y_range_buttons = ttk.Frame(controls)
		y_range_buttons.pack(fill=tk.X, pady=(0, 12))
		ttk.Button(y_range_buttons, text="Apply Y", command=self.apply_y_range).pack(
			side=tk.LEFT, fill=tk.X, expand=True
		)
		ttk.Button(y_range_buttons, text="Reset Y", command=self.reset_y_view).pack(
			side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0)
		)
		self.status = ttk.Label(controls, text="Choose a CSV file to begin.", wraplength=220)
		self.status.pack(fill=tk.X, pady=(12, 0))

		self.figure = Figure(figsize=(8, 5), dpi=100, tight_layout=True)
		self.axes = self.figure.add_subplot(111)
		self.axes.set_title("Select a CSV file to graph")
		self.plot_frame = ttk.Frame(self.root, padding=(0, 12, 12, 12))
		self.plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
		self.canvas = FigureCanvasTkAgg(self.figure, master=self.plot_frame)
		self.toolbar = NavigationToolbar2Tk(self.canvas, self.plot_frame, pack_toolbar=False)
		self.toolbar.update()
		self.toolbar.pack(side=tk.BOTTOM, fill=tk.X)
		self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

	def choose_csv(self):
		raw_data_dir = Path(__file__).resolve().parents[1] / "raw_data"
		selected_path = filedialog.askopenfilename(
			title="Select a CSV file",
			initialdir=raw_data_dir if raw_data_dir.is_dir() else Path.cwd(),
			filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
		)
		if not selected_path:
			return

		try:
			data = pd.read_csv(selected_path, low_memory=False)
		except (OSError, pd.errors.ParserError, UnicodeDecodeError) as error:
			messagebox.showerror("Could not open CSV", str(error), parent=self.root)
			return

		self.data = data
		self.csv_path = Path(selected_path)
		self.date_column = find_date_column(data)
		self.current_x_name = None
		self.full_xlim = None
		self.full_ylim = None
		self.range_start.set("")
		self.range_end.set("")
		self.y_range_start.set("")
		self.y_range_end.set("")
		self.file_label.configure(text=self.csv_path.name)

		x_options = [ROW_NUMBER, *map(str, data.columns)]
		self.x_menu.configure(values=x_options)
		self.x_axis.set(str(self.date_column) if self.date_column is not None else ROW_NUMBER)
		self._update_y_choices()

		numeric_columns = self._numeric_columns()
		self.status.configure(text=f"{len(data):,} rows, {len(data.columns):,} columns")
		if not numeric_columns:
			self.status.configure(text="This CSV has no numeric columns to graph.")
		else:
			self.graph_data()

	def _numeric_columns(self):
		if self.data is None:
			return []
		return [
			column
			for column in self.data.select_dtypes(include="number").columns
			if self.data[column].notna().any()
		]

	def _update_y_choices(self, _event=None):
		self.y_series.delete(0, tk.END)
		x_column = self.x_axis.get()
		columns = [column for column in self._numeric_columns() if str(column) != x_column]
		self.y_series_columns = columns
		for column in columns:
			self.y_series.insert(tk.END, display_series_name(column, self.station_names))
		if columns:
			self.y_series.selection_set(0)

	def _on_x_axis_changed(self, _event=None):
		self._update_y_choices()
		self.graph_data()

	def _on_y_series_selected(self, _event=None):
		self.root.after_idle(self.graph_data)

	def _on_chart_type_changed(self, _event=None):
		self.graph_data()

	def graph_data(self):
		if self.data is None:
			return

		selected_indices = self.y_series.curselection()
		if not selected_indices:
			return

		y_columns = [self.y_series_columns[index] for index in selected_indices]
		x_name = self.x_axis.get()
		preserve_view = self.full_xlim is not None and self.current_x_name == x_name
		previous_xlim = self.axes.get_xlim() if preserve_view else None
		previous_ylim = self.axes.get_ylim() if preserve_view else None
		if not preserve_view:
			self.range_start.set("")
			self.range_end.set("")
		if x_name == ROW_NUMBER:
			x_values = pd.Series(range(len(self.data)), index=self.data.index, name=ROW_NUMBER)
		else:
			x_values = self.data[x_name]
			if x_name == str(self.date_column):
				x_values = pd.to_datetime(x_values, errors="coerce")
		self.current_x_values = x_values

		self.axes.clear()
		plot_method = {
			"Line": self.axes.plot,
			"Scatter": self.axes.scatter,
			"Bar": self.axes.bar,
		}[self.chart_type.get()]

		display_names = [display_series_name(column, self.station_names) for column in y_columns]
		for column, display_name in zip(y_columns, display_names):
			values = pd.to_numeric(self.data[column], errors="coerce")
			plot_data = pd.DataFrame({"x": x_values, "y": values}).dropna()
			if plot_data.empty:
				continue
			if self.chart_type.get() == "Scatter":
				plot_method(plot_data["x"], plot_data["y"], label=display_name, s=12)
			else:
				plot_method(plot_data["x"], plot_data["y"], label=display_name)

		self.axes.set_xlabel(x_name)
		self.axes.set_ylabel(display_names[0] if len(display_names) == 1 else "Value (see legend)")
		self.axes.set_title(self.csv_path.name)
		if len(y_columns) > 1:
			self.axes.legend()
		if pd.api.types.is_datetime64_any_dtype(x_values):
			date_locator = mdates.AutoDateLocator(minticks=4, maxticks=9)
			self.axes.xaxis.set_major_locator(date_locator)
			self.axes.xaxis.set_major_formatter(mdates.ConciseDateFormatter(date_locator))
			self.figure.autofmt_xdate()
		self.full_xlim = self.axes.get_xlim()
		self.full_ylim = self.axes.get_ylim()
		if preserve_view:
			self.axes.set_xlim(previous_xlim)
			self.axes.set_ylim(previous_ylim)
		self.current_x_name = x_name
		self.canvas.draw()
		self.status.configure(text=f"Showing {len(y_columns)} series")

	def apply_x_range(self):
		if self.full_xlim is None or self.current_x_values is None:
			messagebox.showinfo("No graph", "Graph data before applying an X-axis range.", parent=self.root)
			return

		start_text = self.range_start.get().strip()
		end_text = self.range_end.get().strip()
		if not start_text and not end_text:
			messagebox.showinfo("Enter a range", "Enter at least one X-axis boundary.", parent=self.root)
			return

		is_date_axis = pd.api.types.is_datetime64_any_dtype(self.current_x_values)
		try:
			if is_date_axis:
				start = self._date_range_bound(start_text, is_end=False) if start_text else self.full_xlim[0]
				end = self._date_range_bound(end_text, is_end=True) if end_text else self.full_xlim[1]
			else:
				if not pd.api.types.is_numeric_dtype(self.current_x_values):
					raise ValueError("Range inputs require a date or numeric X axis.")
				start = float(start_text) if start_text else self.full_xlim[0]
				end = float(end_text) if end_text else self.full_xlim[1]
			if pd.isna(start) or pd.isna(end) or start >= end:
				raise ValueError("The start boundary must be earlier than the end boundary.")
		except (TypeError, ValueError, OverflowError) as error:
			messagebox.showerror("Invalid X-axis range", str(error), parent=self.root)
			return

		self.axes.set_xlim(start, end)
		self.canvas.draw()
		self.status.configure(text=f"Showing X range: {start_text or 'full start'} to {end_text or 'full end'}")

	@staticmethod
	def _date_range_bound(value, is_end):
		parsed = pd.Timestamp(value)
		if pd.isna(parsed):
			raise ValueError(f"Could not interpret '{value}' as a date.")
		if is_end and len(value) == 10:
			parsed += pd.Timedelta(days=1)
		return mdates.date2num(parsed.to_pydatetime())

	def apply_y_range(self):
		if self.full_ylim is None:
			messagebox.showinfo("No graph", "Graph data before applying a Y-axis range.", parent=self.root)
			return

		start_text = self.y_range_start.get().strip()
		end_text = self.y_range_end.get().strip()
		if not start_text and not end_text:
			messagebox.showinfo("Enter a range", "Enter at least one Y-axis boundary.", parent=self.root)
			return

		try:
			start = float(start_text) if start_text else self.full_ylim[0]
			end = float(end_text) if end_text else self.full_ylim[1]
			if not math.isfinite(start) or not math.isfinite(end) or start >= end:
				raise ValueError("The minimum must be finite and less than the maximum.")
		except ValueError as error:
			messagebox.showerror("Invalid Y-axis range", str(error), parent=self.root)
			return

		self.axes.set_ylim(start, end)
		self.canvas.draw()
		self.status.configure(text=f"Showing Y range: {start_text or 'full minimum'} to {end_text or 'full maximum'}")

	def reset_x_view(self):
		if self.full_xlim is None:
			return
		self.axes.set_xlim(self.full_xlim)
		self.range_start.set("")
		self.range_end.set("")
		self.canvas.draw()
		self.status.configure(text="Reset X axis")

	def reset_y_view(self):
		if self.full_ylim is None:
			return
		self.axes.set_ylim(self.full_ylim)
		self.y_range_start.set("")
		self.y_range_end.set("")
		self.canvas.draw()
		self.status.configure(text="Reset Y axis")


def main():
	root = tk.Tk()
	CsvGraphApp(root)
	root.mainloop()


if __name__ == "__main__":
	main()
