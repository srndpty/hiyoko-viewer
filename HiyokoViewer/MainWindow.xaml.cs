using Microsoft.Win32;
using System;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media.Imaging;
using System.Windows.Interop;
using System.Windows.Forms;
using MaterialDesignThemes.Wpf.AddOns.Utils.Screen; // 追加

namespace HiyokoViewer
{
    public partial class MainWindow : Window
    {
        public MainWindow()
        {
            InitializeComponent();
        }

        private void OpenFileButton_Click(object sender, RoutedEventArgs e)
        {
			var openFileDialog = new OpenFileDialog
			{
				// 対応するファイル形式のフィルタを設定
				Filter = "画像ファイル (*.png;*.jpg;*.jpeg;*.bmp;*.gif)|*.png;*.jpg;*.jpeg;*.bmp;*.gif|全てのファイル (*.*)|*.*"
			};

			if (openFileDialog.ShowDialog() == true)
            {
                // 選択されたファイルのパスから画像を読み込む
                string filePath = openFileDialog.FileName;
                try
                {
                    // BitmapImageを使って画像を読み込み、Imageコントロールに表示
                    var bitmap = new BitmapImage();
                    bitmap.BeginInit();
                    bitmap.UriSource = new Uri(filePath);
                    bitmap.CacheOption = BitmapCacheOption.OnLoad; // ファイルをロックしないようにすぐに読み込む
                    bitmap.EndInit();

                    MainImage.Source = bitmap;
                }
                catch (Exception ex)
                {
                    MessageBox.Show("画像の読み込みに失敗しました: " + ex.Message);
                }
            }
        }

        private void Window_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            if (e.ChangedButton == MouseButton.Left)
                this.DragMove();
        }
    }
}