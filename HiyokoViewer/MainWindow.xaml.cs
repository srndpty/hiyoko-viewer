using Microsoft.Win32;
using System;
using System.Windows;
using System.Windows.Media.Imaging;

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
            OpenFileDialog openFileDialog = new OpenFileDialog();
            // 対応するファイル形式のフィルタを設定
            openFileDialog.Filter = "画像ファイル (*.png;*.jpg;*.jpeg;*.bmp;*.gif)|*.png;*.jpg;*.jpeg;*.bmp;*.gif|全てのファイル (*.*)|*.*";

            if (openFileDialog.ShowDialog() == true)
            {
                // 選択されたファイルのパスから画像を読み込む
                string filePath = openFileDialog.FileName;
                try
                {
                    // BitmapImageを使って画像を読み込み、Imageコントロールに表示
                    BitmapImage bitmap = new BitmapImage();
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
    }
}