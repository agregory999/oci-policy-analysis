#convert source.png -resize 512x512 oc#i-policy-dg-viewer.png
mkdir oci-policy-dg-viewer.iconset
cp oci-policy-dg-viewer.png oci-policy-dg-viewer.iconset/icon_512x512.png
sips -z 256 256 oci-policy-dg-viewer.png --out oci-policy-dg-viewer.iconset/icon_256x256.png
sips -z 128 128 oci-policy-dg-viewer.png --out oci-policy-dg-viewer.iconset/icon_128x128.png
sips -z 32 32 oci-policy-dg-viewer.png --out oci-policy-dg-viewer.iconset/icon_32x32.png
sips -z 16 16 oci-policy-dg-viewer.png --out oci-policy-dg-viewer.iconset/icon_16x16.png
iconutil -c icns oci-policy-dg-viewer.iconset
