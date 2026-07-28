from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, UploadFile, status

from app.core.config import Settings
from app.core.storage_mutation import StorageMutation
from app.core.upload_validation import validate_image_upload, validate_material_upload
from app.integrations.material_asset_store import MaterialAssetStore
from app.models.materials import MaterialRecord
from app.schemas.materials import MaterialCreatePayload, MaterialUpdatePayload


class MaterialsStorageMutationMixin:
    settings: Settings
    asset_store: MaterialAssetStore

    def _apply_payload_to_material(
        self,
        material: MaterialRecord,
        payload: MaterialCreatePayload | MaterialUpdatePayload,
        *,
        file_upload: UploadFile | None,
        previews: list[UploadFile],
        custom_previews: list[UploadFile],
        is_create: bool,
        storage_mutation: StorageMutation,
    ) -> None:
        if file_upload is not None:
            validate_material_upload(
                file_upload,
                max_size_bytes=self.settings.material_file_max_size_bytes,
                missing_detail="请上传有效的资料文件",
                invalid_type_detail="资料文件内容与文件类型不匹配",
                too_large_detail="资料文件不能超过 50MB",
            )
        if len(previews) > self.settings.material_manual_preview_max_images:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="手动预览图最多上传 10 张")
        if len(custom_previews) > self.settings.material_custom_preview_max_images:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="自定义配图最多上传 5 张")
        for preview_file in previews:
            validate_image_upload(
                preview_file,
                settings=self.settings,
                max_size_bytes=self.settings.material_preview_image_max_size_bytes,
                missing_detail="请上传有效的预览图片",
                invalid_type_detail="预览图片仅支持 PNG、JPG、WEBP、GIF、BMP、AVIF、HEIC、HEIF 格式",
                too_large_detail="预览图片不能超过 5MB",
            )
        for preview_file in custom_previews:
            validate_image_upload(
                preview_file,
                settings=self.settings,
                max_size_bytes=self.settings.material_preview_image_max_size_bytes,
                missing_detail="请上传有效的自定义配图",
                invalid_type_detail="自定义配图仅支持 PNG、JPG、WEBP、GIF、BMP、AVIF、HEIC、HEIF 格式",
                too_large_detail="自定义配图不能超过 5MB",
            )
        delivery_method = (payload.deliveryMethod or material.delivery_method or "FILE").upper()
        if delivery_method == "NETDISK" and file_upload is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="网盘交付无需上传站内文件")
        material.title = payload.title.strip()
        material.description = payload.description
        material.price = int(payload.price or 0)
        material.is_free = material.price <= 0
        material.school = payload.school
        material.college = payload.college or None
        material.major = payload.major or None
        material.general_course = bool(payload.generalCourse)
        material.course_category = payload.courseCategory or ("GENERAL" if payload.generalCourse else "MAJOR")
        material.grade_type = payload.gradeType or material.grade_type or "STAGE"
        material.grade_value = payload.gradeValue or material.grade_value or "大一"
        material.keywords = payload.keywords
        material.tags_json = self._json_dumps(self._split_tags(payload.tags))
        material.delivery_method = delivery_method
        material.netdisk_url = payload.netdiskUrl
        material.netdisk_password = payload.netdiskPassword
        material.netdisk_expired_at = payload.netdiskExpiredAt
        material.netdisk_reminder_at = payload.netdiskReminderAt
        material.preview_watermark_enabled = bool(
            payload.previewWatermarkEnabled
            if payload.previewWatermarkEnabled is not None
            else material.preview_watermark_enabled
        )
        material.preview_source = payload.previewSource or material.preview_source or "AUTO"
        material.custom_preview_text = payload.customPreviewText
        material.copyright_owner = payload.copyrightOwner
        material.status = "VISIBLE"
        material.review_status = "APPROVED"
        material.deleted_at = None
        material.updated_at = datetime.now(UTC)

        if file_upload is not None:
            previous_file_key = material.file_storage_key
            key, size = self.asset_store.save_upload(material_id=material.id, slot="file", upload=file_upload)
            storage_mutation.record_new(key)
            storage_mutation.replace_after_commit(previous_file_key)
            material.file_storage_key = key
            material.original_filename = file_upload.filename or material.original_filename
            material.file_size = size
            material.file_type = self._resolve_file_type(file_upload.filename)
        elif is_create and delivery_method == "NETDISK":
            material.file_storage_key = None
            material.original_filename = None
            material.file_size = 0
            material.file_type = "netdisk"

        if delivery_method == "NETDISK":
            storage_mutation.replace_after_commit(material.file_storage_key)
            material.file_storage_key = None
            material.original_filename = (
                None if material.original_filename is None and not self._has_file(material) else material.original_filename
            )
            material.file_size = 0 if material.file_storage_key is None else material.file_size
            material.file_type = "netdisk" if material.file_storage_key is None else material.file_type

        if previews:
            for existing_key in self._loads(material.manual_preview_keys_json):
                if not self._is_external_url(existing_key):
                    storage_mutation.replace_after_commit(existing_key)
            preview_keys = []
            for file in previews:
                preview_key = self.asset_store.save_upload(
                    material_id=material.id,
                    slot="manual-preview",
                    upload=file,
                )[0]
                storage_mutation.record_new(preview_key)
                preview_keys.append(preview_key)
            material.manual_preview_keys_json = self._json_dumps(preview_keys)
        elif is_create:
            material.manual_preview_keys_json = material.manual_preview_keys_json or self._json_dumps([])

        if custom_previews:
            for existing_key in self._loads(material.custom_preview_images_json):
                if not self._is_external_url(existing_key):
                    storage_mutation.replace_after_commit(existing_key)
            custom_keys = []
            for file in custom_previews:
                custom_key = self.asset_store.save_upload(
                    material_id=material.id,
                    slot="custom-preview",
                    upload=file,
                )[0]
                storage_mutation.record_new(custom_key)
                custom_keys.append(custom_key)
            material.custom_preview_images_json = self._json_dumps(custom_keys)
        elif getattr(payload, "customPreviewClear", False):
            for existing_key in self._loads(material.custom_preview_images_json):
                if not self._is_external_url(existing_key):
                    storage_mutation.replace_after_commit(existing_key)
            material.custom_preview_images_json = self._json_dumps([])

        manual_keys = self._loads(material.manual_preview_keys_json)
        if material.preview_source == "MANUAL" and manual_keys:
            material.preview_status = "done"
            material.preview_page_count = len(manual_keys)
            material.preview_pages = len(manual_keys)
        elif (material.file_type or "").lower() == "pdf" and self._has_file(material):
            material.preview_status = "done"
            material.preview_page_count = max(
                int(material.preview_page_count or 0),
                self.settings.material_preview_pages_large,
            )
            material.preview_pages = min(
                material.preview_page_count,
                self.settings.material_preview_pages_small,
            )
        else:
            material.preview_status = "unsupported"
            material.preview_page_count = None
            material.preview_pages = None
        material.preview_manifest = self._json_dumps(
            {
                "status": material.preview_status,
                "pageCount": material.preview_page_count,
                "previewPages": material.preview_pages,
                "pages": [
                    {"index": index + 1, "key": key}
                    for index, key in enumerate(manual_keys)
                    if isinstance(key, str) and key.strip()
                ],
            }
        )

        if delivery_method == "FILE" and not self._has_file(material):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料缺少有效的下载方式")
        if delivery_method == "NETDISK" and not material.netdisk_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料缺少有效的下载方式")
