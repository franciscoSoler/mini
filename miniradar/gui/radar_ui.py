from PyQt5 import QtWidgets
from PyQt5 import QtCore

import numpy as np
import matplotlib.lines as lines
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
import src.common as common
import gui.common_gui as common_gui


class RadarUI(QtWidgets.QWidget, common_gui.CommonGUI):

    update_animation = QtCore.pyqtSignal(animation.FuncAnimation)

    def __init__(self, controller):
        super(RadarUI, self).__init__()
        self.__measure_phase = True
        # self._real_time = False
        # self.__freq_max = 800
        self._controller = controller

        self.__vsup = 0.4
        self.__vinf = 0

        self.__max_freq_amplitude = 0.5
        self.__x_sign_data = self._controller.get_signal_range()
        self.__x_freq_data = self._controller.get_frequency_range()
        self.__img_lims = (0, common.Spectrogram_length, 0, self._controller.get_disance_from_freq(self.__x_freq_data[-1]))
        self.__spectrogram_data = np.zeros((self._controller.freq_length, common.Spectrogram_length))
        self.__figure = plt.figure(figsize=(25,20))

        self.__phase_line = lines.Line2D(np.arange(common.Spectrogram_length), np.zeros(common.Spectrogram_length))
        self.__freq_line = lines.Line2D(self.__x_freq_data, np.zeros(self._controller.freq_length))
        self.__second_plot_line = None

        self.__init_ui()

    def __init_ui(self):

        # if self._real_time:
        #     auto_rewind.hide()
        #     self.__rewind_audio.hide()

        self.__canvas = FigureCanvasQTAgg(self.__figure)
        self.__canvas.show()

        main_layout = QtWidgets.QVBoxLayout()
        main_layout.addWidget(self.__canvas)

        self.setLayout(main_layout)

    def run(self):
        self._ani = animation.FuncAnimation(self.__figure, self.__update_figures, self._controller.run,
                                             blit=False, interval=50, repeat=True,
                                             init_func=self.__init)
        self.update_animation.emit(self._ani)

    def __update_figures(self, data):
        # update the data
        signal, freq, phase = data

        self.__sign_line.set_ydata(signal)

        if self.__measure_phase:
            self.__second_plot_line.set_ydata(np.hstack((self.__second_plot_line.get_ydata()[1:], phase)))
        else:
            self.__second_plot_line.set_ydata(freq)
        self.__spectrogram_data = np.hstack((self.__spectrogram_data[:, 1:], np.transpose([freq])))
        self.__image.set_array(self.__spectrogram_data)

    def __init(self):
        ax_sign = self.__figure.add_subplot(311)
        ax_sign.set_ylim(-1, 1) # TODO change this range
        ax_sign.set_ylabel('Voltage')
        ax_sign.set_xlabel('Time')
        ax_sign.grid()

        self.__sign_line, = ax_sign.plot(self.__x_sign_data, np.zeros(self._controller.signal_length))

        self.__figure.add_subplot(312)
        if self.__measure_phase:
            ax_freq = self.__initialize_phase_plot()
            self.__second_plot_line, = ax_freq.plot(np.arange(common.Spectrogram_length), np.zeros(common.Spectrogram_length))
        else:
            ax_freq = self.__initialize_fft_plot()
            self.__second_plot_line, = ax_freq.plot(self.__x_freq_data, np.zeros(self._controller.freq_length))

        ax_freq.grid()

        ax_spectr = self.__figure.add_subplot(313)
        ax_spectr.set_xlabel('Pulse Number')
        ax_spectr.set_ylabel('Distance')
        ax_spectr.grid(color='white')

        self.__image = ax_spectr.imshow(self.__spectrogram_data, aspect='auto', origin='lower',
                                             interpolation=None, animated=True, vmin=self.__vinf,
                                             vmax=self.__vsup, extent=self.__img_lims)
        self.__figure.colorbar(self.__image)

    def __initialize_fft_plot(self):
        ax_freq = self.__figure.axes[1]
        ax_freq.set_ylim(self.__vinf, self.__max_freq_amplitude)
        ax_freq.set_ylabel('Gain')
        return ax_freq

    def __initialize_phase_plot(self):
        ax_phase = self.__figure.axes[1]
        ax_phase.set_ylim(-180, 180)
        ax_phase.set_ylabel('Phase')
        ax_phase.set_xlabel('Freq')
        return ax_phase

    def plot_phase(self):
        self.__measure_phase = True
        self.__second_plot_line.set_data(self.__phase_line.get_data())

        ax_phase = self.__initialize_phase_plot()
        ax_phase.relim()
        ax_phase.autoscale_view()

    def plot_fft(self):
        self.__measure_phase = False
        self.__second_plot_line.set_data(self.__freq_line.get_data())

        ax_freq = self.__initialize_fft_plot()
        ax_freq.relim()
        ax_freq.autoscale_view()
